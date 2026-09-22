"""本机 OCR、脱敏及还原，CLI 只接触隔离的安全副本"""

import json
import os
import re
import subprocess
from contextlib import nullcontext
from copy import copy

from pydantic import ValidationError

from resume_maker.domain.models import AIResult, Model
from resume_maker.infrastructure.observability import operation, record
from resume_maker.integrations.local_ocr import REVIEW_SCORE, read_document
from resume_maker.integrations.privacy_store import PrivacyStore
from resume_maker.integrations.providers.base import Cancelled, ProviderError, StructuredOutputError
from resume_maker.integrations.providers.cli import run_cli
from resume_maker.integrations.providers.sandbox import native_executable
from resume_maker.integrations.source_access import SourceAccess


def structured_text(message: str) -> str:
    """只解开唯一完整 JSON 代码块，多个结果、块外数据和截断回复仍交由严格校验拒绝"""
    if message.count("```") != 2:
        return message
    fenced = re.search(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", message, flags=re.DOTALL)
    if fenced and not re.search(r"[{}\[\]]", message[: fenced.start()] + message[fenced.end() :]):
        return fenced.group(1)
    return message


def schema(result_model: type[Model]) -> dict:
    """把结果模型转换为严格 JSON Schema，使输出字段完整且禁止额外键"""
    value = result_model.model_json_schema()

    def strict(node):
        """递归清除默认值并将对象的所有属性设为必填"""
        if isinstance(node, dict):
            node.pop("default", None)
            if "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for child in node.values():
                strict(child)
        elif isinstance(node, list):
            for child in node:
                strict(child)

    strict(value)
    return value


class CodexProvider:
    """用脱敏副本和严格读取权限保留 CLI 的分析及鉴权方式"""

    supports_images = False
    preprocess_images = True

    def __init__(self, *, environment=None, privacy=None, runner=None):
        """测试注入 CLI 替身，生产通过版本校验和受限材料工具调用"""
        self.environment = dict(environment or {})
        self.privacy = privacy or PrivacyStore()
        self.runner = runner or run_cli
        self.sensitive_values = set()

    def with_private_data(self, value):
        """为当前任务登记尚未保存的资料，独立副本避免并发互相污染"""
        result = copy(self)
        redactor = self.privacy.redactor()
        redactor.learn(value)
        result.sensitive_values = self.sensitive_values | redactor.values
        return result

    def register_ocr(self, document):
        """在模板任务的独立 Provider 中登记 OCR 原文和需要整体遮盖的片段"""
        redactor = self.privacy.redactor()
        redactor.learn(document["text"])
        self.sensitive_values = (
            self.sensitive_values
            | redactor.values
            | {
                row["text"]
                for page in document["pages"]
                for row in page["blocks"]
                if row["confidence"] < REVIEW_SCORE
            }
        )

    @staticmethod
    def executable(settings):
        """解析实际运行及版本检查使用的原生程序"""
        return native_executable(settings.executable)

    def inspect(self, settings):
        """检查本机 CLI 版本，不连接模型或读取用户文档"""
        try:
            result = subprocess.run(
                [self.executable(settings), "--version"],
                capture_output=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            return {
                "available": result.returncode == 0
                and result.stdout.strip() == "codex-cli 0.154.0",
                "version": result.stdout.strip(),
                "authentication": "使用已验证的 CLI 0.154.0，复用文件登录及只读材料工具",
            }
        except (OSError, subprocess.TimeoutExpired, ProviderError):
            return {"available": False, "error": "无法读取 CLI 版本。"}

    def run(self, **kwargs):
        """使用经历结果契约调用统一隐私出口"""
        return self.run_structured(result_model=AIResult, **kwargs)

    @operation("provider.run_structured", "ai")
    def run_structured(
        self,
        *,
        result_model,
        workspace,
        prompt,
        thread_id,
        settings,
        cancelled,
        emit,
        images=None,
        sensitive_values=(),
        sources=None,
        data_dir=None,
    ):
        """原图只供本机 OCR，脱敏后的文字进入独立 CLI 沙箱"""
        if cancelled.is_set():
            raise Cancelled("请求已取消。")
        redactor = self.privacy.redactor()
        redactor.values.update(self.sensitive_values)
        redactor.values.update(value for value in sensitive_values if value)
        documents = []
        for path in images or []:
            emit("status", {"text": "正在本机提取文档文字，原图不外发"})
            document = read_document(path, cancelled)
            redactor.learn(document["text"])
            for page in document["pages"]:
                for block in page["blocks"]:
                    if block["confidence"] < REVIEW_SCORE:
                        redactor.values.add(block["text"])
            documents.append(document)
        safe_prompt = redactor.prompt(prompt)
        if documents:
            safe_prompt += (
                "\n本地 OCR 文字和比例坐标（低置信度片段已整体替换，禁止推测）：\n"
                + json.dumps(redactor.protect(documents), ensure_ascii=False)
            )
        safe_schema = redactor.protect_schema(schema(result_model))
        payload = {
            "transport": "codex-cli-sandbox",
            "input": safe_prompt,
            "schema": safe_schema,
        }
        if len(json.dumps(payload).encode()) > 2 * 1024 * 1024:
            raise ProviderError("脱敏请求超过大小限制，请缩小材料范围。")
        identifier = self.privacy.record(payload, redactor.count)
        record("ai", "context", "发送给模型的脱敏上下文", {**payload, "model": settings.model})
        emit("status", {"text": f"隐私保护已处理 {redactor.count} 处内容，正在发送文字请求"})
        try:

            def audit(name, result, count):
                """记录有界的脱敏工具结果，原始路径和还原表始终留在内存"""
                self.privacy.material(identifier, name, result, count)

            with (
                SourceAccess(sources, data_dir, redactor, cancelled, audit)
                if sources
                else nullcontext(None)
            ) as access:
                options = {"source_access": access} if access is not None else {}
                raw = self.runner(payload, settings, self.environment, cancelled, emit, **options)
            if cancelled.is_set():
                raise Cancelled("请求已取消。")
            try:
                restored = redactor.restore(json.loads(structured_text(raw)))
                result = result_model.model_validate(restored)
            except ValidationError as exc:
                raise StructuredOutputError(
                    json.dumps(restored, ensure_ascii=False),
                    exc.errors(include_url=False, include_context=False),
                ) from exc
            except ValueError as exc:
                raise ProviderError("模型输出不是完整 JSON，结果未采用。") from exc
            self.privacy.finish(identifier, "completed")
            return result
        except Exception:
            self.privacy.finish(identifier, "cancelled" if cancelled.is_set() else "failed")
            raise
