"""定义返回结构化建议的 AI 适配器接口"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from resume_maker.domain.models import AIResult, Model, ProviderSettings


class ProviderError(Exception):
    """上游 AI 适配器执行或结果校验失败"""

    pass


class Cancelled(ProviderError):
    """任务被主动取消，调用方应停止发布其结果"""

    pass


@dataclass(frozen=True)
class MosaicImage:
    """模板内嵌图片的本机原件，必须经过隐私出口打码后才能成为模型附件"""

    node: str
    data: bytes = field(repr=False)


@dataclass(frozen=True)
class PageImage:
    """图片模板的本机页面，只能在隐私出口生成脱敏版面后发送"""

    path: Path = field(repr=False)


class StructuredOutputError(ProviderError):
    """模型已返回但结构不合法，保留有界字段反馈供调用方重试，不能当作有效结果"""

    def __init__(self, response, errors):
        """只提取路径、错误类别和有限片段，避免把整个嵌套方案放进每条反馈"""
        super().__init__("Codex 返回的数据不符合要求的格式，原有内容未被修改。")
        self.response = response
        self.issues = [
            {
                "path": ".".join(map(str, error.get("loc", ()))),
                "type": error["type"],
                "message": error["msg"][:600],
                "value": str(error.get("input", ""))[:200],
            }
            for error in errors[:20]
        ]


class Provider(Protocol):
    """可注入的 AI 执行接口，生产出口负责脱敏及隔离模型工具"""

    def run(
        self,
        *,
        workspace: Path,
        prompt: str,
        thread_id: str | None,
        settings: ProviderSettings,
        cancelled: threading.Event,
        emit: Callable[[str, dict], None],
        sources: list[dict] | None = None,
        data_dir: Path | None = None,
    ) -> AIResult:
        """按给定上下文生成建议并通过事件回调报告进度、响应取消"""
        ...

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
        images: list[Path | MosaicImage | PageImage] | None = None,
        sources: list[dict] | None = None,
        data_dir: Path | None = None,
    ) -> T:
        """复用同一 AI 配置生成指定领域模型，用于模板映射等独立分析"""
        ...
