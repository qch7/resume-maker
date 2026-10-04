"""插件注册、类型化能力和资源作用域协议"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ServiceKey[T]:
    """公共接口的稳定标识和协议版本"""

    name: str
    version: str = "1.0.0"


class Context(Protocol):
    """插件只能消费清单声明的依赖和登记自己拥有的贡献"""

    instance_id: str
    generation: int

    def require(self, key: ServiceKey[T]) -> T:
        """读取已声明的公开依赖"""
        ...

    def provide(self, key: ServiceKey[T], value: T) -> None:
        """登记属于当前插件的唯一能力"""
        ...

    def effect(self, dispose: Callable[[], None]) -> None:
        """登记随实例逆序释放的幂等资源"""
        ...
