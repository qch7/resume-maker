"""后台调用可以读取本轮独立实例，任务上下文不会跨线程复用"""

from collections.abc import Callable
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass

from resume_maker.sdk.manifest import InstanceSpec


@dataclass(frozen=True)
class TaskContext:
    """公开任务身份和有声明约束的实例服务读取入口"""

    id: str
    generation: int
    require: Callable


active_task: ContextVar[TaskContext | None] = ContextVar("resume_plugin_task", default=None)


def current_task() -> TaskContext:
    """离开实际执行线程后不能继续使用任务上下文"""
    value = active_task.get()
    if value is None:
        raise RuntimeError("当前不在插件任务作用域中")
    return value


def task_metadata(value):
    """先固定实例声明，避免排队后的调用方修改任务配置或破坏租约查询"""
    result = deepcopy(value)
    specs = result.get("plugin_instances", [])
    if not isinstance(specs, list) or len(specs) > 100:
        raise ValueError("任务实例清单无效或超过 100 项")
    if specs:
        result["plugin_instances"] = [
            InstanceSpec.model_validate(item).model_dump() for item in specs
        ]
    return result
