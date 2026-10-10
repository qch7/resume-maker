"""凭据的限用途借用协议，普通配置只保存不透明引用"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol


class Credentials[T](Protocol):
    """可信 Host 插件按实例身份和声明用途借用凭据"""

    def register(
        self, adapter: str, purpose: str, loader: Callable[[], AbstractContextManager[T]]
    ) -> str:
        """登记临时加载器，引用在当前宿主关闭时撤销"""
        ...

    def borrow(self, identifier: str, adapter: str, purpose: str) -> AbstractContextManager[T]:
        """借用范围内读取原值，退出后不得保存到配置或日志"""
        ...

    def revoke(self, identifier: str) -> None:
        """撤销引用并阻止后续借用，已有执行仍需实际完成"""
        ...


class CredentialManagement(Protocol):
    """宿主密码编辑入口创建持久引用，原文不返回客户端"""

    def save(self, adapter: str, purpose: str, secret: str) -> str:
        """按实例及用途独立保存并返回新引用"""
        ...
