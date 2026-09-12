"""AI 适配器契约：返回结构化建议，不能直接修改经历版本。"""

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from resume_maker.domain.models import AIResult, ProviderSettings


class ProviderError(Exception):
    """上游 AI 适配器执行或结果校验失败。"""

    pass


class Cancelled(ProviderError):
    """任务被主动取消，调用方应停止发布其结果。"""

    pass


class Provider(Protocol):
    """可注入的 AI 执行接口，隔离模型调用与经历持久化。"""

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
        """按给定上下文生成建议，并通过事件回调报告进度、响应取消。"""
        ...
