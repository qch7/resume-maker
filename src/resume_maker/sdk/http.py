"""可信插件的有界 HTTP 服务，截止时间使用 time.monotonic 的绝对值"""

import threading
from dataclasses import dataclass, field
from typing import Protocol

from resume_maker.sdk.model import ProviderError


class HTTPError(ProviderError):
    """传输、等待预算或响应资源边界失败，不包含鉴权及供应商正文"""


@dataclass(frozen=True)
class HTTPResponse:
    """完整读取的有界响应，状态码由插件按供应商契约解释"""

    status: int
    headers: dict[str, str]
    body: bytes = field(repr=False)


class HTTPClient(Protocol):
    """连接池及同配额键的并发限制归属宿主，不暴露普通配置中的密码"""

    def request(
        self,
        method: str,
        url: str,
        *,
        deadline: float,
        cancelled: threading.Event,
        quota: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        max_bytes: int = 4 * 1024 * 1024,
    ) -> HTTPResponse:
        """等待配额、连接及响应共用截止预算，取消后等待实际传输清理"""
        ...
