"""注册事务、依赖授权和可回收插件实例"""

import importlib
import importlib.util
import re
import sys
import threading
from collections.abc import Callable
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TypeVar, cast

from resume_maker.runtime.graph import PluginError, Resolution, available_selection, resolve
from resume_maker.runtime.instances import definition_id, expand_instances
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
        self.plugin_id = host.definition_id(self.instance_id)
        self.scope_id = host.scope_id
        self.config = deepcopy(host.configs.get(manifest.id, manifest.config))
        self.scope = Scope()
        self.starters: list[Callable[[], None]] = []
        self.before_deactivate: list[Callable[[], None]] = []
        self.health_checks: list[Callable[[], None]] = []
        self._data = None
        self.state = "activating"

    @property
    def data(self):
        """从声明的存储能力取得固定命名空间，停止后使旧句柄失效"""
        if self._data is None:
            if self.scope.closed or self.state in {"draining", "stopped", "cleanup-failed"}:
                raise PluginError("插件实例已经停止")
            factory = self.require(ServiceKey("storage.instances"))
            self._data = factory(
                self.instance_id, self.scope_id, self.manifest.instances.scope == "task"
            )
            self.effect(self._data.close)
        return self._data

    def require(self, key: ServiceKey[T]) -> T:
        """仅允许清单声明的硬依赖、可选依赖和本插件能力"""
        allowed = (
            self.manifest.requires.get("host", {}).keys()
            | self.manifest.optional.keys()
            | self.manifest.provides.get("host", {}).keys()
        )
        if key.name not in allowed:
            raise PluginError(f"{self.instance_id} 未声明能力依赖 {key.name}")
        if key.name in self.manifest.provides.get(
            "host", {}
        ) and key.name not in self.manifest.requires.get("host", {}):
            return self.host.service_values[(self.instance_id, key.name)]
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
        if self.instance_id != self.plugin_id:
            local = identifier.removeprefix(self.plugin_id + "/")
            identifier = f"{self.instance_id}/{local}"
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

    def health(self, check: Callable[[], None]) -> None:
        """发布前执行只读健康检查，异常使整个候选实例回收"""
        self.health_checks.append(check)

    def task_scope(self, identifier, instances, configs=None):
        """任务实例继承工作区能力，权限只能在当前所有者授权范围内收窄"""
        return self.host.open_scope(
            "task",
            identifier,
            instances,
            configs=configs,
            permissions=set(self.manifest.permissions),
        )


class Host:
    """一个工作区的插件宿主，注册成功才允许外部发布"""

    def __init__(
        self,
        manifests: dict[str, Manifest],
        selected: set[str],
        required: set[str],
        bootstrap: dict[str, object] | None = None,
        generation: int = 1,
        *,
        instance_specs=(),
        scope="workspace",
        scope_id="default",
        parent=None,
    ):
        """先求解纯清单，再持有应用独立的注册集"""
        self.definitions = dict(manifests)
        self.manifests, self.instance_specs = expand_instances(
            manifests, instance_specs, missing_ok=True
        )
        self.parent, self.scope_kind, self.scope_id = parent, scope, scope_id
        if not isinstance(scope_id, str) or not re.fullmatch(r"[\w.-]{1,200}", scope_id):
            raise PluginError("作用域须使用稳定标识，不得包含目录分隔符")
        self.children = {}
        self.scope_lock = threading.RLock()
        self.closing = False
        self.frozen_scopes = set()
        self.inherited = set()
        if parent:
            self.inherited = {
                key
                for key in parent.selected
                if parent.manifests[key].instances.scope == "application"
                or scope == "task"
                and parent.manifests[key].instances.scope == "workspace"
            }
            for key in self.inherited:
                if key in selected:
                    raise PluginError(f"子作用域不能替换继承实例：{key}")
                self.manifests[key] = parent.manifests[key]
                if key in parent.instance_specs:
                    self.instance_specs[key] = parent.instance_specs[key]
        for key in selected:
            if key not in self.manifests:
                raise PluginError(f"插件尚未安装：{key}")
            lifetime = self.manifests[key].instances.scope
            if lifetime != scope and not (parent is None and lifetime == "application"):
                raise PluginError(f"{key} 必须在 {lifetime} 作用域创建")
        self.selected, self.required = set(selected) | self.inherited, set(required)
        self.resolution: Resolution = resolve(self.manifests, self.selected, required)
        self.generation = generation
        self.bootstrap = bootstrap or {}
        self.configs = deepcopy(self.bootstrap.get("configs", {}))
        self.configuration = deepcopy(self.bootstrap.get("configuration"))
        self.desired = set(selected)
        self.blocked: dict[str, str] = {}
        self.services: dict[str, object] = {}
        self.service_values: dict[tuple[str, str], object] = {}
        self.contributions: dict[tuple[str, str], Contribution] = {}
        self.instances: dict[str, PluginContext] = {}
        self.rpc_handlers: dict[tuple[str, str], Callable] = {}
        self.started = False
        self.initializing = False
        if parent:
            self.instances.update({key: parent.instances[key] for key in self.inherited})
            self.service_values.update(
                {
                    key: value
                    for key, value in parent.service_values.items()
                    if key[0] in self.inherited
                }
            )
            self.services.update(
                {
                    name: parent.service_values[(owner, name)]
                    for name, owner in self.resolution.providers.items()
                    if owner in self.inherited
                }
            )
            self.contributions.update(
                {
                    key: item
                    for key, item in parent.contributions.items()
                    if item.owner in self.inherited
                }
            )

    def definition_id(self, identifier):
        """获取实例对应的不可变插件定义身份"""
        return definition_id(self.instance_specs, identifier)

    def package_location(self, identifier):
        """同一定义的多个实例共用已校验代码，不共用运行状态"""
        return self.bootstrap.get("packages", {}).get(self.definition_id(identifier))

    def open_scope(
        self,
        kind,
        identifier,
        instances,
        *,
        configs=None,
        permissions=None,
        bootstrap=None,
        leased=False,
        generation=None,
    ):
        """候选子作用域健康后登记，关闭失败保留父能力和子作用域诊断"""
        if kind not in {"workspace", "task"} or self.scope_kind == "task":
            raise PluginError("只能由应用或工作区创建工作区和任务作用域")
        with self.scope_lock:
            if self.closing:
                raise PluginError("父作用域正在关闭")
            if self.frozen_scopes and not leased:
                raise PluginError("插件正在切换，暂不能创建新的子作用域")
            if (kind, identifier) in self.children:
                raise PluginError(f"作用域已经存在：{kind}/{identifier}")
            manifests, specs = expand_instances(self.definitions, instances)
            selected = set(specs)
            if permissions is not None and any(
                set(manifests[key].permissions) - permissions for key in selected
            ):
                raise PluginError("子作用域请求超过父授权的权限")
            from resume_maker.runtime.configuration import (
                compose_configuration,
                configurations,
                replacement_layer,
            )

            values = {
                **self.bootstrap,
                **(bootstrap or {}),
                "configs": configurations(manifests, configs or {}),
                "configuration": compose_configuration(
                    manifests, [replacement_layer(kind, configs or {})]
                ),
            }
            if kind == "workspace" and "config" in values:
                directory = values["config"].data_dir.resolve()
                owners = ([self] if "db" in self.services else []) + [
                    child for child in self.children.values() if child.scope_kind == "workspace"
                ]
                if any(
                    "config" in owner.bootstrap
                    and owner.bootstrap["config"].data_dir.resolve() == directory
                    for owner in owners
                ):
                    raise PluginError("独立工作区必须使用不同数据目录")
            # 协调器和数据同步回调归当前工作区，不能沿用父对象
            values.pop("plugin_manager", None)
            values.pop("synchronize_data", None)
            child = Host(
                self.definitions,
                selected,
                set(),
                values,
                self.generation if generation is None else generation,
                instance_specs=instances,
                scope=kind,
                scope_id=identifier,
                parent=self,
            )
            try:
                child.activate()
                child.start()
            except BaseException:
                try:
                    child.close()
                except Exception:
                    self.children[(kind, identifier)] = child
                    raise
                raise
            self.children[(kind, identifier)] = child
            return child

    def close_scope(self, kind, identifier):
        """实际释放成功后才从父容器移除作用域"""
        with self.scope_lock:
            child = self.children[(kind, identifier)]
            child.close()
            self.children.pop((kind, identifier))

    def active_scopes(self, affected):
        """变更协调器等待所有引用受影响服务的子作用域实际关闭"""
        with self.scope_lock:
            return [
                {"kind": kind, "id": key}
                for (kind, key), child in self.children.items()
                if child.inherited & affected or child.selected & affected
            ]

    @contextmanager
    def task_context(self, record):
        """执行和回收共同持有任务作用域，失败清理继续作为切换阻断条件"""
        from resume_maker.sdk.tasks import TaskContext, active_task

        metadata = record.get("metadata", {})
        specs = metadata.get("plugin_instances", [])
        identifier = record["id"]
        child = None
        token = None
        try:
            if specs:
                if metadata.get("plugin_lock") != self.task_lock(specs):
                    raise PluginError("任务插件版本已变化，请明确重试")
                owner = self.instances[record["owner"]]
                child = self.open_scope(
                    "task",
                    identifier,
                    specs,
                    configs=metadata.get("plugin_configs", {}),
                    permissions=set(owner.manifest.permissions),
                    leased=True,
                    generation=record["generation"],
                )

            def require(instance, key):
                """服务只能通过本轮实例声明读取，已结束的上下文拒绝旧引用"""
                if child is None or child.closing or instance in child.inherited:
                    raise PluginError("当前任务实例不可用")
                return child.instances[instance].require(key)

            token = active_task.set(TaskContext(identifier, record["generation"], require))
            yield
        finally:
            if token is not None:
                active_task.reset(token)
            if child is not None:
                self.close_scope("task", identifier)

    def task_lock(self, instances):
        """记录实例代码和清单摘要，执行前不能悄悄切换已排队的实现"""
        from resume_maker.runtime.state import fingerprint

        return {
            item["plugin"]: {
                "manifest": fingerprint(self.definitions[item["plugin"]].model_dump()),
                "artifact": self.package_location(item["plugin"]).name
                if self.package_location(item["plugin"])
                else None,
            }
            for item in instances
        }

    def prepare_task(self, metadata, owner):
        """持久化调度意图前验证任务组合、配置和授权，不执行插件入口"""
        from resume_maker.runtime.configuration import configurations

        specs = metadata.get("plugin_instances", [])
        if not specs:
            return metadata
        manifests, parsed = expand_instances(self.definitions, specs)
        allowed = set(self.instances[owner].manifest.permissions)
        if any(set(manifests[key].permissions) - allowed for key in parsed):
            raise PluginError("任务实例请求超过父授权的权限")
        candidate = Host(
            self.definitions,
            set(parsed),
            set(),
            self.bootstrap,
            self.generation,
            instance_specs=specs,
            scope="task",
            parent=self,
        )
        for key in parsed:
            if missing := candidate.missing_dependencies(key):
                raise PluginError(f"任务插件缺少依赖：{'; '.join(missing)}")
        configs = configurations(manifests, metadata.get("plugin_configs", {}))
        return {
            **metadata,
            "plugin_configs": {key: configs[key] for key in parsed},
            "plugin_lock": self.task_lock(specs),
        }

    def check_health(self):
        """检查所有本地实例，检查失败不会发布部分就绪结果"""
        for key in self.resolution.order:
            if key not in self.inherited:
                for check in self.instances[key].health_checks:
                    check()

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
            {
                key: self.bootstrap.get("worker_environments", {}).get(self.definition_id(key), {})
                for key in self.manifests
            },
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
                if identifier in self.selected and identifier not in self.inherited:
                    self.activate_one(identifier)
            self.check_health()
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
                location = self.package_location(identifier)
                if location:
                    path = (location / module).resolve()
                    if not path.is_relative_to(location) or path.suffix != ".py":
                        raise PluginError("外部宿主入口必须是包内 Python 文件")
                    definition = self.definition_id(identifier).replace(".", "_")
                    namespace = f"resume_plugin_{location.name}_{definition}"
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

                location = self.package_location(identifier)
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
        environment = self.bootstrap.get("worker_environments", {}).get(
            self.definition_id(identifier), {}
        )
        return check_dependencies(self.manifests[identifier], versions=environment.get("versions"))

    def start(self) -> None:
        """启动已验证实例，部分失败时逆序停止已持有资源"""
        if self.started:
            return
        try:
            for identifier in self.resolution.order:
                if identifier in self.inherited:
                    continue
                for start in self.instances[identifier].starters:
                    start()
            self.check_health()
            self.started = True
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        """逆依赖关闭并报告真实清理结果"""
        errors, protected = [], set()
        with self.scope_lock:
            self.closing = True
            for key in list(self.children):
                self.close_scope(*key)
        for identifier in reversed(self.resolution.order):
            if identifier in protected or identifier in self.inherited:
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
                "plugin": self.definition_id(identifier),
                "scope": manifest.instances.scope,
                "scope_id": self.scope_id,
                "multiple": manifest.instances.multiple,
                "title": manifest.title,
                "version": manifest.version,
                "required": identifier in self.required,
                "installed": True,
                "builtin": self.package_location(identifier) is None,
                "environment_lock": manifest.environment_lock,
                "enabled": identifier in self.selected,
                "desired": identifier in self.desired,
                "config": deepcopy(self.configs.get(identifier, manifest.config)),
                "config_schema": manifest.config_schema,
                "config_provenance": (self.configuration or {})
                .get("provenance", {})
                .get(identifier, {}),
                "reason": self.blocked.get(identifier),
                "state": "blocked"
                if identifier in self.blocked
                else self.instances[identifier].state
                if identifier in self.instances
                else "disabled",
                "provides": list(manifest.provides.get("host", {})),
                "requires": manifest.requires.get("host", {}),
                "dependencies": manifest.requires,
                "provided": manifest.provides,
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
