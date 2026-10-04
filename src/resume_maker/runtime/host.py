"""注册事务、依赖授权和可回收插件实例"""

import importlib
import importlib.util
import sys
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TypeVar, cast

from resume_maker.runtime.graph import PluginError, Resolution, available_selection, resolve
from resume_maker.runtime.packages import check_dependencies
from resume_maker.sdk.context import ServiceKey
from resume_maker.sdk.manifest import Dependency, Manifest

T = TypeVar("T")


@dataclass
class Scope:
    """逆序关闭全部已登记资源，清理失败仍保留未完成的资源归属"""

    disposers: list[Callable[[], None]] = field(default_factory=list)
    barriers: list[Callable[[], None]] = field(default_factory=list)
    closed: bool = False

    def close(self) -> None:
        """重复释放只重试此前失败的步骤，不重复关闭成功资源"""
        pending, errors = [], []
        for stop in reversed(self.barriers):
            try:
                stop()
            except Exception as exc:
                pending.append(stop)
                errors.append(exc)
        self.barriers = list(reversed(pending))
        if errors:
            raise ExceptionGroup("插件后台执行尚未停止，保留其依赖资源", errors)
        failed, errors = [], []
        for dispose in reversed(self.disposers):
            try:
                dispose()
            except Exception as exc:
                failed.append(dispose)
                errors.append(exc)
        self.disposers = list(reversed(failed))
        self.closed = not failed
        if errors:
            raise ExceptionGroup("插件资源清理失败", errors)


@dataclass(frozen=True)
class Contribution:
    """具有唯一身份和顺序的可撤销扩展项"""

    owner: str
    point: str
    identifier: str
    value: object
    order: int = 0


class PluginContext:
    """按清单限制注册和消费范围，资源归属当前实例"""

    def __init__(self, host: "Host", manifest: Manifest):
        """创建尚未对请求发布的候选注册作用域"""
        self.host, self.manifest = host, manifest
        self.instance_id, self.generation = manifest.id, host.generation
        self.config = deepcopy(host.configs.get(manifest.id, manifest.config))
        self.scope = Scope()
        self.starters: list[Callable[[], None]] = []
        self.before_deactivate: list[Callable[[], None]] = []
        self.state = "activating"

    def require(self, key: ServiceKey[T]) -> T:
        """仅允许清单声明的硬依赖、可选依赖和本插件能力"""
        allowed = (
            self.manifest.requires.get("host", {}).keys()
            | self.manifest.optional.keys()
            | self.manifest.provides.get("host", {}).keys()
        )
        if key.name not in allowed:
            raise PluginError(f"{self.instance_id} 未声明能力依赖 {key.name}")
        owners = self.host.resolution.bindings.get((self.instance_id, "host", key.name))
        if key.name in self.host.resolution.collections:
            if owners is None:
                owners = self.host.resolution.collections[key.name]
            values = tuple(self.host.service_values[(owner, key.name)] for owner in owners)
            dependency = self.manifest.requires.get("host", {}).get(key.name)
            if (
                isinstance(dependency, str)
                or isinstance(dependency, Dependency)
                and dependency.cardinality == "one"
            ):
                return values[0]
            return values
        return self.host.require(key)

    def provide(self, key: ServiceKey[T], value: T) -> None:
        """注册清单承诺的能力，拒绝隐式和重复服务"""
        spec = self.manifest.provides.get("host", {}).get(key.name)
        if spec is None or spec.version != key.version:
            raise PluginError(f"{self.instance_id} 未声明唯一能力 {key.name}@{key.version}")
        identity = (self.instance_id, key.name)
        if identity in self.host.service_values:
            raise PluginError(f"能力重复注册：{identity}")
        self.host.service_values[identity] = value
        self.effect(lambda: self.host.service_values.pop(identity, None))
        if spec.cardinality == "many":
            return
        if key.name in self.host.services:
            raise PluginError(f"能力重复注册：{key.name}")
        self.host.services[key.name] = value
        self.effect(lambda: self.host.services.pop(key.name, None))

    def contribute(self, point: str, identifier: str, value: object, order: int = 0) -> None:
        """登记有序集合项，释放作用域时撤销对应贡献"""
        if identifier not in self.manifest.contributes.get(point, []):
            raise PluginError(f"{self.instance_id} 未声明贡献 {point}/{identifier}")
        key = (point, identifier)
        if key in self.host.contributions:
            raise PluginError(f"贡献重复注册：{point}/{identifier}")
        self.host.contributions[key] = Contribution(
            self.instance_id, point, identifier, value, order
        )
        self.effect(lambda: self.host.contributions.pop(key, None))

    def effect(self, dispose: Callable[[], None]) -> None:
        """保存外部资源的回收入口，注册失败时同样执行"""
        self.scope.disposers.append(dispose)

    def rpc(self, method: str, handler: Callable) -> None:
        """登记清单声明的远程操作，HTTP 和隔离界面均经过同一 DTO 校验"""
        key = (self.instance_id, method)
        if method not in self.manifest.rpc or key in self.host.rpc_handlers:
            raise PluginError(f"未声明或重复的远程操作：{key}")
        self.host.rpc_handlers[key] = handler
        self.effect(lambda: self.host.rpc_handlers.pop(key, None))

    def lifecycle(self, start: Callable[[], None], stop: Callable[[], None]) -> None:
        """后台执行只在所有能力完成校验后启动"""
        self.starters.append(start)
        self.scope.barriers.append(stop)


class Host:
    """一个工作区的插件宿主，注册成功才允许外部发布"""

    def __init__(
        self,
        manifests: dict[str, Manifest],
        selected: set[str],
        required: set[str],
        bootstrap: dict[str, object] | None = None,
        generation: int = 1,
    ):
        """先求解纯清单，再持有应用独立的注册集"""
        self.manifests, self.selected, self.required = manifests, selected, required
        self.resolution: Resolution = resolve(manifests, selected, required)
        self.generation = generation
        self.bootstrap = bootstrap or {}
        self.configs = deepcopy(self.bootstrap.get("configs", {}))
        self.desired = set(selected)
        self.blocked: dict[str, str] = {}
        self.services: dict[str, object] = {}
        self.service_values: dict[tuple[str, str], object] = {}
        self.contributions: dict[tuple[str, str], Contribution] = {}
        self.instances: dict[str, PluginContext] = {}
        self.rpc_handlers: dict[tuple[str, str], Callable] = {}
        self.started = False
        self.initializing = False

    def block_unavailable(self, reasons):
        """启动期间保留不可写扩展的资料和期望选择，仅阻断其依赖闭包"""
        if not reasons:
            return
        if not self.initializing:
            raise PluginError("候选插件资料不兼容：" + "; ".join(reasons.values()))
        selected, blocked = available_selection(
            self.manifests,
            self.selected,
            self.required,
            {**self.blocked, **reasons},
            self.bootstrap.get("worker_environments"),
        )
        self.selected, self.blocked = selected, blocked
        self.resolution = resolve(self.manifests, selected, self.required)

    def require(self, key: ServiceKey[T]) -> T:
        """宿主通过明确能力键取得当前注册值"""
        if key.name not in self.services:
            raise PluginError(f"能力不可用：{key.name}")
        return cast(T, self.services[key.name])

    def collection(self, point: str) -> tuple[Contribution, ...]:
        """按显式顺序和稳定标识返回当前集合快照"""
        return tuple(
            sorted(
                (item for item in self.contributions.values() if item.point == point),
                key=lambda item: (item.order, item.identifier),
            )
        )

    def activate(self) -> None:
        """按依赖顺序导入已选入口，任何失败均回收候选注册"""
        self.initializing = True
        try:
            for identifier in self.resolution.order:
                if missing := self.missing_dependencies(identifier):
                    raise PluginError(f"{identifier} 缺少安装依赖：{'; '.join(missing)}")
            for identifier in self.resolution.order:
                if identifier in self.selected:
                    self.activate_one(identifier)
        except BaseException:
            self.close()
            raise
        finally:
            self.initializing = False

    def activate_one(self, identifier: str) -> None:
        """创建独立作用域并核对入口实际提供的服务"""
        manifest = self.manifests[identifier]
        context = PluginContext(self, manifest)
        self.instances[identifier] = context
        try:
            if missing := self.missing_dependencies(identifier):
                raise PluginError(f"{identifier} 缺少安装依赖：{'; '.join(missing)}")
            if entry := manifest.entrypoints.get("host"):
                module, separator, name = entry.entry.partition(":")
                if not separator:
                    raise PluginError(f"入口需要 module:function：{entry.entry}")
                location = self.bootstrap.get("packages", {}).get(identifier)
                if location:
                    path = (location / module).resolve()
                    if not path.is_relative_to(location) or path.suffix != ".py":
                        raise PluginError("外部宿主入口必须是包内 Python 文件")
                    namespace = f"resume_plugin_{location.name}_{identifier.replace('.', '_')}"
                    loaded = sys.modules.get(namespace)
                    if loaded is None:
                        spec = importlib.util.spec_from_file_location(namespace, path)
                        loaded = importlib.util.module_from_spec(spec)
                        sys.modules[namespace] = loaded
                        try:
                            spec.loader.exec_module(loaded)
                        except BaseException:
                            sys.modules.pop(namespace, None)
                            raise
                    activate = getattr(loaded, name)
                else:
                    activate = getattr(importlib.import_module(module), name)
                activate(context)
            if entry := manifest.entrypoints.get("worker"):
                from resume_maker.runtime.worker import activate_worker

                location = self.bootstrap.get("packages", {}).get(identifier)
                if location is None:
                    raise PluginError("worker 必须来自已校验的插件包")
                activate_worker(context, entry, location)
            for name in manifest.provides.get("host", {}):
                if (identifier, name) not in self.service_values:
                    raise PluginError(f"{identifier} 没有提供声明的能力 {name}")
            context.state = "active"
        except BaseException:
            context.state = "failed"
            raise

    def missing_dependencies(self, identifier):
        """worker 使用自己已准备的环境，共享 Host 仍校验当前解释器"""
        environment = self.bootstrap.get("worker_environments", {}).get(identifier, {})
        return check_dependencies(self.manifests[identifier], versions=environment.get("versions"))

    def start(self) -> None:
        """启动已验证实例，部分失败时逆序停止已持有资源"""
        if self.started:
            return
        try:
            for identifier in self.resolution.order:
                for start in self.instances[identifier].starters:
                    start()
            self.started = True
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        """逆依赖关闭并报告真实清理结果"""
        errors, protected = [], set()
        for identifier in reversed(self.resolution.order):
            if identifier in protected:
                continue
            if context := self.instances.get(identifier):
                context.state = "draining"
                try:
                    context.scope.close()
                    context.state = "stopped"
                except Exception as exc:
                    context.state = "cleanup-failed"
                    errors.append(exc)
                    pending = list(self.resolution.edges[identifier])
                    while pending:
                        dependency = pending.pop()
                        if dependency not in protected:
                            protected.add(dependency)
                            pending.extend(self.resolution.edges[dependency])
        self.started = False
        if errors:
            raise ExceptionGroup("宿主仍有未释放资源", errors)

    def status(self) -> list[dict]:
        """分别报告已安装、所选和实际运行状态"""
        return [
            {
                "id": identifier,
                "title": manifest.title,
                "version": manifest.version,
                "required": identifier in self.required,
                "installed": True,
                "builtin": identifier not in self.bootstrap.get("packages", {}),
                "environment_lock": manifest.environment_lock,
                "enabled": identifier in self.selected,
                "desired": identifier in self.desired,
                "config": deepcopy(self.configs.get(identifier, manifest.config)),
                "config_schema": manifest.config_schema,
                "reason": self.blocked.get(identifier),
                "state": "blocked"
                if identifier in self.blocked
                else self.instances[identifier].state
                if identifier in self.instances
                else "disabled",
                "provides": list(manifest.provides.get("host", {})),
                "requires": manifest.requires.get("host", {}),
                "permissions": manifest.permissions,
                "lifecycle": manifest.lifecycle.model_dump(),
            }
            for identifier, manifest in sorted(self.manifests.items())
        ] + [
            {
                "id": key,
                "title": key,
                "version": "unknown",
                "required": False,
                "installed": False,
                "enabled": False,
                "desired": True,
                "state": "blocked",
                "reason": self.blocked[key],
                "provides": [],
                "requires": {},
                "permissions": [],
            }
            for key in sorted(self.desired - self.manifests.keys())
        ]
