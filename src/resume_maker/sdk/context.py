"""插件注册、类型化能力和资源作用域协议"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from resume_maker.sdk.storage import InstanceData

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class ServiceKey[T]:
    """公共接口的稳定标识和协议版本"""

    name: str
    version: str = "1.0.0"


class Context(Protocol):
    """插件只能消费清单声明的依赖和登记自己拥有的贡献"""

    instance_id: str
    plugin_id: str
    scope_id: str
    generation: int
    config: dict[str, object]

    @property
    def data(self) -> InstanceData:
        """读取属于当前实例的资料，须声明 storage.instances 依赖"""
        ...

    def require(self, key: ServiceKey[T]) -> T:
        """读取已声明的公开依赖"""
        ...

    def provide(self, key: ServiceKey[T], value: T) -> None:
        """登记属于当前插件的唯一能力"""
        ...

    def effect(self, dispose: Callable[[], None]) -> None:
        """登记随实例逆序释放的幂等资源"""
        ...

    def contribute(self, point: str, identifier: str, value: object, order: int = 0) -> None:
        """登记清单声明的贡献，随当前实例撤销"""
        ...

    def rpc(self, method: str, handler: Callable[[T], R]) -> None:
        """登记接收单个载荷并返回结果的操作，输入输出按清单校验"""
        ...

    def lifecycle(self, start: Callable[[], None], stop: Callable[[], None]) -> None:
        """全部注册验证后启动，停止须等待后台执行真正结束"""
        ...

    def health(self, check: Callable[[], None]) -> None:
        """登记发布前必须通过的只读检查"""
        ...
