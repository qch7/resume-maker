"""基于代次和窗口确认的插件变更计划"""

import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

from resume_maker.core.errors import Problem
from resume_maker.runtime.capability_selection import select_capability_group
from resume_maker.runtime.configuration import (
    compose_configuration,
    replacement_layer,
    workspace_layers,
)
from resume_maker.runtime.graph import PluginError, resolve
from resume_maker.runtime.instances import definition_id, expand_instances
from resume_maker.runtime.policy import WINDOW_LEASE_SECONDS, PluginPolicy
from resume_maker.runtime.state import fingerprint


class PluginManager:
    """协调配置、依赖、在途请求和浏览器草稿，不让超时代替确认"""

    def __init__(self, host, store, profiles=None, *, policy=None):
        """每个宿主持有独立计划、窗口和请求租约"""
        self.host, self.store = host, store
        self.policy = policy or PluginPolicy()
        self.profiles = deepcopy(profiles or {})
        self.lock = threading.RLock()
        self.plans, self.windows, self.requests = store.recover_plans(), {}, {}
        self.frozen: set[str] = set()
        self.maintenance = False
        self.publish_routes = None
        self.pending_plan = None
        self.next_window_number = 1

    def package_lock(self):
        """锁定插件清单及协议版本，不在启动时自动取最新版本"""
        return {
            identifier: {
                "version": manifest.version,
                "manifest_sha256": fingerprint(manifest.model_dump()),
                "artifact_sha256": self.host.bootstrap.get("packages", {}).get(identifier).name
                if identifier in self.host.bootstrap.get("packages", {})
                else None,
            }
            for identifier, manifest in sorted(self.host.definitions.items())
        }

    def validate_packages(self, selected, specs=None):
        """应用前重新核验已授权产物，安装后的磁盘修改也使旧计划失效"""
        store = self.host.bootstrap.get("package_store")
        if store is None:
            return
        records = store.records()
        selected = {
            definition_id(self.host.instance_specs if specs is None else specs, key)
            for key in selected
        }
        for identifier in selected & self.host.bootstrap.get("packages", {}).keys():
            if identifier not in records:
                raise PluginError(f"插件安装记录已被移除：{identifier}")
            manifest, location = store._discover_one(identifier, records[identifier])
            if (
                manifest != self.host.definitions[identifier]
                or location != self.host.bootstrap["packages"][identifier]
            ):
                raise PluginError(f"插件代码已更新，请先重启并重新生成计划：{identifier}")

    def save_plan(self, plan):
        """提交前持久化失败阻止变更，提交后保留配置作为最终恢复判据"""
        try:
            self.store.save_plan(plan)
        except OSError:
            if plan["state"] not in {"committed", "restart-required"}:
                raise

    def install(self, path, digest, trusted_modes):
        """新包可供下一次计划选装，已知包代码更新只在宿主重启后装载"""
        with self.lock:
            if self.pending_plan or self.maintenance:
                raise Problem("插件变更期间不能安装代码，请先完成当前计划。", 409)
            store = self.host.bootstrap["package_store"]
            inspection = store.inspect(path)
            identifier = inspection["manifest"]["id"]
            if identifier in store.records() and store.records()[identifier]["digest"] != digest:
                raise PluginError("已有插件的新版本须通过联合候选计划验证后切换")
            result = store.install(path, digest, set(trusted_modes))
            identifier = result["id"]
            if identifier in self.host.manifests:
                return {**result, "restart_required": True}
            manifests, locations = store.discover()
            self.host.manifests[identifier] = manifests[identifier]
            self.host.definitions[identifier] = manifests[identifier]
            self.host.bootstrap["packages"][identifier] = locations[identifier]
            return {**result, "restart_required": False}

    def uninstall(self, identifier):
        """移除安装引用后保留数据目录和清理记录"""
        with self.lock:
            if self.pending_plan or self.maintenance:
                raise Problem("插件变更期间不能卸载代码，请先完成当前计划。", 409)
            active = {self.host.definition_id(key) for key in self.host.selected}
            tasks = self.host.services.get("tasks")
            if tasks and tasks.active({identifier}):
                raise PluginError("插件仍有活动任务，请先取消并等待结束")
            for child in self.host.children.values():
                active.update(child.definition_id(key) for key in child.selected)
            result = self.host.bootstrap["package_store"].uninstall(identifier, active)
            self.host.manifests.pop(identifier, None)
            self.host.definitions.pop(identifier, None)
            self.host.bootstrap["packages"].pop(identifier, None)
            return result

    def select_capability(self, group, enabled, selected, expected_generation, instances=None):
        """能力开关只返回候选，保留活动组合、实例配置及全部资料"""
        with self.lock:
            self._generation(expected_generation)
            if self.pending_plan or self.maintenance:
                raise Problem("请先完成当前插件变更。", 409)
            specs = list(self.host.instance_specs.values()) if instances is None else instances
            manifests, _ = expand_instances(self.host.definitions, specs)
            return {
                "selected": select_capability_group(
                    manifests, selected, self.host.required, group, enabled
                )
            }

    def plan(
        self,
        selected,
        expected_generation,
        configs=None,
        instances=None,
        config_edits=(),
        *,
        package_updates=None,
        data_intents=(),
    ):
        """解析候选组合及反向依赖闭包，计划尚不改变活动能力"""
        with self.lock:
            self._generation(expected_generation)
            selected = set(selected)
            from resume_maker.runtime.host import Host

            specs = list(self.host.instance_specs.values()) if instances is None else instances
            definitions = dict(self.host.definitions)
            package_updates = package_updates or {}
            packages = self.host.bootstrap.get("package_store")
            for owner, record in package_updates.items():
                definitions[owner], _ = packages._discover_one(owner, record)
            candidate_host = Host(
                definitions,
                selected,
                self.host.required,
                self.host.bootstrap,
                self.host.generation,
                instance_specs=specs,
            )
            manifests, parsed = candidate_host.manifests, candidate_host.instance_specs
            self.validate_packages(selected, parsed)
            resolution = candidate_host.resolution
            if set(configs or {}) - manifests.keys():
                raise PluginError("配置引用未知插件实例")
            if any(edit["instance"] not in manifests for edit in config_edits):
                raise PluginError("字段操作引用未知插件实例")
            layers = (self.host.configuration or {}).get(
                "layers", [replacement_layer("workspace", self.host.configs)]
            )
            configuration = compose_configuration(
                manifests,
                workspace_layers(layers, configs, config_edits),
                missing_ok=True,
            )
            candidate = configuration["configs"]
            for key in selected:
                if missing := candidate_host.missing_dependencies(key):
                    if package_updates and manifests[key].environment_lock:
                        continue
                    raise PluginError(f"{key} 缺少安装依赖：{'; '.join(missing)}")
            changed = self.host.selected ^ selected
            configured = {
                key
                for key in selected & self.host.selected
                if candidate[key] != self.host.configs.get(key, self.host.manifests[key].config)
                or manifests[key] != self.host.manifests[key]
            }
            changed |= configured
            changed.update(
                key
                for key in selected | self.host.selected
                if definition_id(parsed, key) in package_updates
            )
            affected = set(changed)
            graphs = (self.host.resolution.edges, resolution.edges)
            while True:
                previous = set(affected)
                for graph in graphs:
                    affected.update(
                        key for key, dependencies in graph.items() if dependencies & affected
                    )
                if previous == affected:
                    break
            mode = "drain"
            all_manifests = {**self.host.manifests, **manifests}
            if any(all_manifests[key].lifecycle.toggle == "host-restart" for key in changed):
                mode = "host-restart"
            if any(manifests[key].lifecycle.config_update == "host-restart" for key in configured):
                mode = "host-restart"
            if package_updates:
                mode = "host-restart"
            if mode == "host-restart":
                affected = selected | self.host.selected
            value = {
                "id": str(uuid4()),
                "generation": expected_generation,
                "selected": sorted(selected),
                "affected": sorted(affected),
                "added": sorted(selected - self.host.selected),
                "removed": sorted(self.host.selected - selected),
                "mode": mode,
                "expires_at": time.time() + self.policy.plan_lifetime_seconds,
                "lock": self.package_lock(),
                "windows": sorted(self.windows),
                "new_permissions": {
                    key: manifests[key].permissions for key in selected - self.host.selected
                },
                "data_policy": "retain",
                "state": "planned",
                "configs": candidate,
                "configuration": configuration,
                "configured": sorted(configured),
                "instances": [item.model_dump() for item in parsed.values()],
                **(
                    {
                        "package_updates": package_updates,
                        "data_intents": list(data_intents),
                        "automatic_code_rollback": not bool(data_intents),
                        "packages_before": packages.records(),
                        "pins": packages.pins(),
                    }
                    if mode == "host-restart"
                    else {}
                ),
            }
            value["digest"] = fingerprint(value)
            self.plans[value["id"]] = value
            self.save_plan(value)
            return deepcopy(value)

    def prepare_environment(self, identifier):
        """准备环境仅添加候选解释器，活动进程和插件不会原地更新依赖"""
        with self.lock:
            if self.pending_plan or self.maintenance:
                raise Problem("请先完成当前插件变更。", 409)
            packages = self.host.bootstrap["package_store"]
            record = packages.records().get(identifier)
            if record is None:
                raise Problem("插件没有外部安装记录。", 404)
            manifest, location = packages._discover_one(identifier, record)
            result = self.host.bootstrap["environment_store"].prepare(
                manifest,
                location,
                self.host.services["execution"],
                self.host.services["sandbox"],
                tuple(
                    self.host.manifests[key]
                    for key in sorted(self.host.selected)
                    if key != identifier
                ),
            )
            return {
                **result,
                "restart_required": True,
                "launch": [
                    result["python"],
                    "-m",
                    "resume_maker",
                    "--data-dir",
                    str(self.store.path.parent),
                ]
                if result["mode"] == "host"
                else None,
            }

    def _generation(self, expected):
        """旧窗口或并发管理操作不能覆盖当前组合"""
        if expected != self.host.generation:
            raise Problem("插件配置已变化，请重新加载能力清单；本地输入仍保留。", 409)

    def _identified_plan(self, identifier, digest):
        """核对计划身份，退出准备状态不依赖提交有效期或磁盘包状态"""
        plan = self.plans.get(identifier)
        if plan is None or plan["digest"] != digest:
            raise Problem("变更计划不存在或摘要不匹配。", 409)
        return plan

    def _plan(self, identifier, digest):
        """核对代次、摘要、有效期和当前包状态"""
        plan = self._identified_plan(identifier, digest)
        self._generation(plan["generation"])
        _, parsed = expand_instances(
            self.host.definitions, plan.get("instances", []), missing_ok=True
        )
        self.validate_packages(set(plan["selected"]), parsed)
        if plan["expires_at"] < time.time() or plan["lock"] != self.package_lock():
            raise Problem("变更计划已失效，请重新生成。", 409)
        if plan["state"] not in {"planned", "preparing"}:
            raise Problem("变更计划已经结束。", 409)
        if "package_updates" in plan:
            packages = self.host.bootstrap["package_store"]
            if packages.records() != plan["packages_before"] or packages.pins() != plan["pins"]:
                raise Problem("安装目录或版本锁已变化，请重新生成联合计划。", 409)
            for owner, record in plan["package_updates"].items():
                packages._discover_one(owner, record)
        return plan

    def prepare(self, identifier, digest):
        """冻结受影响业务写入，草稿刷新通道继续开放"""
        with self.lock:
            plan = self._plan(identifier, digest)
            if plan["state"] == "preparing":
                return self.progress(identifier)
            if self.pending_plan and self.pending_plan != identifier:
                raise Problem("另一个插件变更正在准备。", 409)
            if sorted(self.windows) != plan["windows"]:
                raise Problem("已连接窗口发生变化，请重新生成计划。", 409)
            with self.host.scope_lock:
                self.frozen = set(plan["affected"])
                self.host.frozen_scopes = set(self.frozen)
            self.pending_plan = identifier
            plan["state"] = "preparing"
            self.save_plan(plan)
            for window in self.windows.values():
                window["pending_plan"] = identifier
                window["acknowledged"] = False
            return self.progress(identifier)

    def progress(self, identifier):
        """显示未确认窗口和在途请求，超时窗口不会自动被移除"""
        plan = self.plans.get(identifier)
        if plan is None:
            raise Problem("变更计划不存在。", 404)
        if plan["state"] in {"applying", "booting"}:
            import json

            saved = json.loads(
                (self.store.operations / (identifier + ".json")).read_text(encoding="utf-8")
            )
            plan = saved
            self.plans[identifier] = plan
        tasks = self.host.services.get("tasks")
        return {
            **plan,
            "waiting_windows": [
                key
                for key in plan["windows"]
                if plan["state"] == "preparing"
                and (key not in self.windows or not self.windows[key]["acknowledged"])
            ],
            "inflight": sum(
                count
                for owner, count in self.requests.items()
                if owner in plan["affected"] and owner != "sys.plugins"
            ),
            "tasks": tasks.active(set(plan["affected"])) if tasks else [],
            "windows_detail": {key: dict(self.windows.get(key, {})) for key in plan["windows"]},
            "scopes": self.host.active_scopes(set(plan["affected"])),
        }

    def cancel_tasks(self, identifier, digest):
        """过期准备计划仍可取消当前任务，取消后仍等待执行真实结束"""
        with self.lock:
            plan = self._identified_plan(identifier, digest)
            self._generation(plan["generation"])
            if plan["state"] != "preparing" or self.pending_plan != identifier:
                raise Problem("请先准备变更。", 409)
            self.host.services["tasks"].cancel_owned(set(plan["affected"]))
            return self.progress(identifier)

    def window(self, identifier, generation, *, title=None, status=None):
        """窗口心跳同时取得冻结通知，过时代次不得自动刷新旧草稿"""
        with self.lock:
            self._generation(generation)
            if identifier not in self.windows:
                plan = self.plans.get(self.pending_plan)
                if self.maintenance or (plan and plan["state"] != "preparing"):
                    raise Problem("插件正在切换，请稍后重新协商。", 409)
                if plan:
                    updated = {**plan, "windows": [*plan["windows"], identifier]}
                    self.save_plan(updated)
                    plan.update(updated)
                self.windows[identifier] = {
                    "pending_plan": self.pending_plan,
                    "acknowledged": False,
                    "number": self.next_window_number,
                }
                self.next_window_number += 1
            window = self.windows[identifier]
            if title is not None:
                window["title"] = title.strip()
            if status is not None:
                window["status"] = status.strip()
            window["last_seen"] = time.time()
            window["connected"] = True
            return dict(window)

    def disconnect(self, identifier, generation):
        """断连只标记状态，未保存输入仍需恢复或明确保留副本"""
        with self.lock:
            self._generation(generation)
            if window := self.windows.get(identifier):
                window["connected"] = False

    def retain_window(self, identifier, plan_id, generation):
        """用户明确保留断连窗口恢复副本后解除等待，不重放旧代次草稿"""
        with self.lock:
            self._generation(generation)
            window = self.windows.get(identifier)
            if not window or window["pending_plan"] != plan_id:
                raise Problem("窗口没有对应的计划。", 409)
            if window.get("connected") and time.time() - window["last_seen"] < WINDOW_LEASE_SECONDS:
                raise Problem("该窗口仍在线，请在窗口中完成草稿保存。", 409)
            window["acknowledged"] = True
            window["recovery_retained"] = True

    def acknowledge(self, identifier, plan_id, generation):
        """窗口只有在领域草稿和最终工作区草稿均落盘后才能确认"""
        with self.lock:
            self._generation(generation)
            window = self.windows.get(identifier)
            if not window or window["pending_plan"] != plan_id:
                raise Problem("窗口没有对应的草稿刷新请求。", 409)
            window["acknowledged"] = True

    def close_window(self, identifier, generation):
        """正常关闭必须先完成持久化；准备期间保留确认记录"""
        with self.lock:
            self._generation(generation)
            if self.frozen:
                raise Problem("请先确认当前草稿刷新。", 409)
            self.windows.pop(identifier, None)

    @contextmanager
    def request(self, owner, *, write, flush=False, generation=None, route_generation=None):
        """请求取得配置租约，代次过期或维护期拒绝业务写入"""
        with self.lock:
            if route_generation is not None:
                self._generation(route_generation)
            if write and generation is not None:
                self._generation(generation)
            if (self.maintenance and owner != "sys.plugins") or (
                write and owner != "sys.plugins" and owner in self.frozen and not flush
            ):
                raise Problem("插件正在切换，请保留输入并等待草稿确认。", 409)
            self.requests[owner] = self.requests.get(owner, 0) + 1
        try:
            yield
        finally:
            with self.lock:
                self.requests[owner] -= 1

    def abort(self, identifier, digest):
        """提交前始终允许取消，仅解除当前计划的冻结并保留已保存草稿"""
        with self.lock:
            plan = self._identified_plan(identifier, digest)
            if plan["state"] not in {"planned", "preparing"}:
                raise Problem("变更计划已经结束。", 409)
            updated = {**plan, "state": "cancelled"}
            self.save_plan(updated)
            plan.update(updated)
            if self.pending_plan != identifier:
                return
            self.frozen.clear()
            with self.host.scope_lock:
                self.host.frozen_scopes.clear()
            self.pending_plan = None
            for window in self.windows.values():
                window.update(pending_plan=None, acknowledged=False)

    def apply(self, identifier, digest):
        """排空完成后切换注册集合，失败时重建仍兼容的旧组合"""
        with self.lock:
            plan = self._plan(identifier, digest)
            if plan["state"] != "preparing":
                raise Problem("请先准备变更并刷新所有窗口的草稿。", 409)
            progress = self.progress(identifier)
            if (
                progress["waiting_windows"]
                or progress["inflight"]
                or progress["tasks"]
                or progress["scopes"]
            ):
                raise Problem("仍有窗口草稿或请求未确认，变更尚未应用。", 409)
            if plan["mode"] == "host-restart":
                return self.upgrades.start(plan)
            if plan["mode"] == "backup-restore":
                from resume_maker.runtime.backup_restore import start_restore

                return start_restore(self, plan)
            self.store.begin(plan)
            self._switch(plan)
            return {"generation": self.host.generation, "state": "committed"}

    def _switch(self, plan):
        """候选注册失败时回收新作用域，旧代码兼容时恢复旧实例"""
        host = self.host
        old_selected, old_resolution = set(host.selected), host.resolution
        old_generation = host.generation
        old_configs, old_desired = host.configs, host.desired
        old_configuration = host.configuration
        old_manifests, old_specs = host.manifests, host.instance_specs
        affected = set(plan["affected"])
        new_selected = set(plan["selected"])
        manifests, specs = expand_instances(
            host.definitions, plan.get("instances", []), missing_ok=True
        )
        resolution = resolve(manifests, new_selected, host.required)
        self.maintenance = True
        try:
            for key in reversed(old_resolution.order):
                if key in affected:
                    for prepare in host.instances[key].before_deactivate:
                        prepare()
            host.deactivate(affected, remove=True)
            host.selected, host.resolution = new_selected, resolution
            host.manifests, host.instance_specs = manifests, specs
            host.configs, host.desired = deepcopy(plan["configs"]), set(new_selected)
            host.configuration = deepcopy(plan["configuration"])
            host.generation += 1
            if synchronize := host.bootstrap.get("synchronize_data"):
                synchronize(new_selected)
            for key in resolution.order:
                if key in affected:
                    host.activate_one(key)
                    if host.started:
                        for start in host.instances[key].starters:
                            start()
            host.check_health()
            if self.publish_routes:
                self.publish_routes()
            self.store.commit(
                new_selected,
                host.generation,
                self.package_lock(),
                host.configs,
                instances=plan.get("instances", []),
                config_layers=plan["configuration"]["layers"],
            )
            plan["state"] = "committed"
            self.save_plan(plan)
        except Exception as exc:
            self.store.failed(type(exc).__name__)
            try:
                # 旧组合尚未排空时仍用旧依赖图，候选开始激活后才使用新图
                # 清理失败立即停止，保留失败实例及尚未释放的依赖
                host.deactivate(affected, remove=True)
                host.selected, host.resolution, host.generation = (
                    old_selected,
                    old_resolution,
                    old_generation,
                )
                host.configs, host.desired = old_configs, old_desired
                host.configuration = old_configuration
                host.manifests, host.instance_specs = old_manifests, old_specs
                for key in old_resolution.order:
                    if key in affected and key not in host.instances:
                        host.activate_one(key)
                        if host.started:
                            for start in host.instances[key].starters:
                                start()
                host.check_health()
                if self.publish_routes:
                    self.publish_routes()
            except Exception as rollback:
                plan["state"] = "recovery-required"
                plan["message"] = "插件切换及回滚失败，请停止宿主后重新启动此前组合。"
                self.save_plan(plan)
                raise PluginError("插件切换及回滚失败，工作区保持维护状态") from rollback
            plan["state"] = "failed"
            self.save_plan(plan)
            self.maintenance = False
            raise Problem(f"插件切换失败，已恢复此前组合：{type(exc).__name__}", 409) from exc
        else:
            self.maintenance = False
            self.windows.clear()
        finally:
            if not self.maintenance:
                self.frozen.clear()
                with self.host.scope_lock:
                    self.host.frozen_scopes.clear()
                self.pending_plan = None
                for window in self.windows.values():
                    window.update(pending_plan=None, acknowledged=False)
