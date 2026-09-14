"""Codex CLI 调用、严格输出校验及进程生命周期管理。"""

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

import psutil

from resume_maker.domain.models import AIResult, Model, ProviderSettings
from resume_maker.integrations.providers.base import Cancelled, ProviderError
from resume_maker.integrations.sources import redact


def schema(result_model: type[Model]) -> dict:
    """把结果模型转换为严格 JSON Schema，使输出字段完整且禁止额外键。"""
    value = result_model.model_json_schema()

    def strict(node):
        """递归清除默认值，并将对象的所有属性设为必填。"""
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


def terminate_tree(process: subprocess.Popen):
    """终止本次请求的子进程树，忽略已经退出的进程。"""
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
        psutil.wait_procs(children + [parent], timeout=3)
    except psutil.NoSuchProcess:
        pass


class CodexProvider:
    """将统一 AI 请求适配为当前用户配置下的 Codex CLI 调用。"""

    @staticmethod
    def executable(settings: ProviderSettings) -> str:
        """解析用户配置的 Codex 可执行文件路径，缺失时给出设置提示。"""
        candidate = shutil.which(settings.executable)
        if not candidate:
            raise ProviderError("找不到 Codex CLI，请在设置中填写已安装的 codex 可执行文件路径。")
        return candidate

    def inspect(self, settings: ProviderSettings) -> dict:
        """读取 CLI 版本以判断程序是否可执行，实际鉴权由连接测试确认。"""
        try:
            executable = self.executable(settings)
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            return {
                "available": result.returncode == 0,
                "executable": executable,
                "version": result.stdout.strip(),
                "authentication": "实际连接测试确认",
            }
        except (OSError, subprocess.TimeoutExpired, ProviderError) as exc:
            return {"available": False, "error": str(exc)}

    def run(
        self,
        *,
        workspace: Path,
        prompt: str,
        thread_id: str | None,
        settings: ProviderSettings,
        cancelled: threading.Event,
        emit: Callable[[str, dict], None],
    ) -> AIResult:
        """使用经历结果模型调用通用结构化执行器。"""
        return self.run_structured(
            result_model=AIResult,
            workspace=workspace,
            prompt=prompt,
            thread_id=thread_id,
            settings=settings,
            cancelled=cancelled,
            emit=emit,
        )

    def run_structured[T: Model](
        self,
        *,
        result_model: type[T],
        workspace: Path,
        prompt: str,
        thread_id: str | None,
        settings: ProviderSettings,
        cancelled: threading.Event,
        emit: Callable[[str, dict], None],
    ) -> T:
        """以只读沙箱调用 Codex，解析 JSON 事件并处理超时、取消和进程回收。"""
        workspace.mkdir(parents=True, exist_ok=True)
        schema_path = workspace / "response-schema.json"
        schema_path.write_text(json.dumps(schema(result_model)), encoding="utf-8")
        command = [
            self.executable(settings),
            "exec",
            "--sandbox",
            "read-only",
            "--json",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "-C",
            str(workspace),
        ]
        if settings.model:
            command += ["--model", settings.model]
        if settings.profile:
            command += ["--profile", settings.profile]
        if thread_id:
            command += ["resume", thread_id]
        command.append("-")
        # 继承当前用户的配置和鉴权；CLI 登录状态无法代表自定义 Provider 的实际连通性。
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=workspace,
            creationflags=0x08000200 if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        lines = queue.Queue()

        def read(stream, channel):
            """在线程中读取标准输出或错误输出，并用结束标记通知主循环。"""
            try:
                for line in stream:
                    lines.put((channel, line))
            finally:
                lines.put((channel, None))

        for stream, channel in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            threading.Thread(target=read, args=(stream, channel), daemon=True).start()
        started, finished, last_message = time.monotonic(), set(), ""
        errors, diagnostics = [], []
        try:
            process.stdin.write(prompt)
            process.stdin.close()
            while len(finished) < 2:
                if cancelled.is_set():
                    raise Cancelled("任务已取消")
                if time.monotonic() - started > settings.timeout_seconds:
                    raise ProviderError(
                        f"Codex 超过 {settings.timeout_seconds} 秒未完成，任务已停止。"
                    )
                try:
                    channel, line = lines.get(timeout=0.2)
                except queue.Empty:
                    continue
                if line is None:
                    finished.add(channel)
                    continue
                if channel == "stderr":
                    diagnostics = (diagnostics + [redact(line.strip())])[-20:]
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                kind = event.get("type")
                if kind == "thread.started":
                    emit("thread", {"id": event["thread_id"]})
                elif kind == "turn.completed":
                    emit("usage", event.get("usage", {}))
                elif kind in {"turn.failed", "error"}:
                    detail = event.get("error", event.get("message", event))
                    errors.append(redact(json.dumps(detail, ensure_ascii=False)))
                elif kind in {"item.started", "item.completed"}:
                    item = event.get("item", {})
                    item_type = item.get("type")
                    if item_type == "agent_message" and kind == "item.completed":
                        last_message = item.get("text", "")
                    elif item_type in {"command_execution", "mcp_tool_call", "web_search"}:
                        emit(
                            "activity",
                            {
                                "type": item_type,
                                "state": kind.split(".")[1],
                                "text": redact(item.get("command", item_type))[:2000],
                            },
                        )
            code = process.wait(timeout=5)
            if code != 0 or errors:
                raise ProviderError("\n".join(errors or diagnostics[-5:]) or f"Codex 退出码 {code}")
            try:
                return result_model.model_validate_json(last_message)
            except ValueError as exc:
                raise ProviderError("Codex 返回的数据不符合要求的格式，原有内容未被修改。") from exc
        finally:
            if process.poll() is None:
                terminate_tree(process)
            for stream in (process.stdout, process.stderr):
                stream.close()
