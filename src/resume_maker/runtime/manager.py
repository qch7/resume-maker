"""基于代次和窗口确认的插件变更计划"""

import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

from resume_maker.core.errors import Problem
from resume_maker.runtime.configuration import configurations
from resume_maker.runtime.graph import PluginError, resolve
from resume_maker.runtime.state import fingerprint


class PluginManager:
    """协调配置、依赖、在途请求和浏览器草稿，不让超时代替确认"""

    def __init__(self, host, store, profiles=None):
        """每个宿主持有独立计划、窗口和请求租约"""
        self.host, self.store = host, store
        self.profiles = deepcopy(profiles or {})
        self.lock = threading.RLock()
        self.plans, self.windows, self.requests = store.recover_plans(), {}, {}
        self.frozen: set[str] = set()
        self.maintenance = False
        self.publish_routes = None
        self.pending_plan = None

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
            for identifier, manifest in sorted(self.host.manifests.items())
        }

    def validate_packages(self, selected):
        """应用前重新核验已授权产物，安装后的磁盘修改也使旧计划失效"""
        store = self.host.bootstrap.get("package_store")
        if store is None:
            return
        records = store.records()
        for identifier in selected & self.host.bootstrap.get("packages", {}).keys():
            if identifier not in records:
                raise PluginError(f"插件安装记录已被移除：{identifier}")
            manifest, location = store._discover_one(identifier, records[identifier])
            if (
                manifest != self.host.manifests[identifier]
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
            result = store.install(path, digest, set(trusted_modes))
            identifier = result["id"]
            if identifier in self.host.manifests:
                return {**result, "restart_required": True}
            manifests, locations = store.discover()
            self.host.manifests[identifier] = manifests[identifier]
            self.host.bootstrap["packages"][identifier] = locations[identifier]
            return {**result, "restart_required": False}

    def uninstall(self, identifier):
        """移除安装引用后保留数据目录和清理记录"""
        with self.lock:
            if self.pending_plan or self.maintenance:
                raise Problem("插件变更期间不能卸载代码，请先完成当前计划。", 409)
            result = self.host.bootstrap["package_store"].uninstall(identifier, self.host.selected)
            self.host.manifests.pop(identifier, None)
            self.host.bootstrap["packages"].pop(identifier, None)
            return result

    def plan(self, selected, expected_generation, configs=None):
        """解析候选组合及反向依赖闭包，计划尚不改变活动能力"""
        with self.lock:
            self._generation(expected_generation)
            selected = set(selected)
            self.validate_packages(selected)
            resolution = resolve(self.host.manifests, selected, self.host.required)
            candidate = configurations(
                self.host.manifests, self.host.configs if configs is None else configs
            )
            for key in selected:
                if missing := self.host.missing_dependencies(key):
                    raise PluginError(f"{key} 缺少安装依赖：{'; '.join(missing)}")
            changed = self.host.selected ^ selected
            configured = {
                key
                for key in selected & self.host.selected
                if candidate[key] != self.host.configs.get(key, self.host.manifests[key].config)
            }
            changed |= configured
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
            if any(self.host.manifests[key].lifecycle.toggle == "host-restart" for key in changed):
                mode = "host-restart"
            if any(
                self.host.manifests[key].lifecycle.config_update == "host-restart"
                for key in configured
            ):
                mode = "host-restart"
            value = {
                "id": str(uuid4()),
                "generation": expected_generation,
                "selected": sorted(selected),
                "affected": sorted(affected),
                "added": sorted(selected - self.host.selected),
                "removed": sorted(self.host.selected - selected),
                "mode": mode,
                "expires_at": time.time() + 600,
                "lock": self.package_lock(),
                "windows": sorted(self.windows),
                "new_permissions": {
                    key: self.host.manifests[key].permissions
                    for key in selected - self.host.selected
                },
                "data_policy": "retain",
                "state": "planned",
                "configs": candidate,
                "configured": sorted(configured),
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

    def _plan(self, identifier, digest):
        """核对代次、摘要、有效期和当前包状态"""
        plan = self.plans.get(identifier)
        if plan is None or plan["digest"] != digest:
            raise Problem("变更计划不存在或摘要不匹配。", 409)
        self._generation(plan["generation"])
        self.validate_packages(set(plan["selected"]))
        if plan["expires_at"] < time.time() or plan["lock"] != self.package_lock():
            raise Problem("变更计划已失效，请重新生成。", 409)
        if plan["state"] not in {"planned", "preparing"}:
            raise Problem("变更计划已经结束。", 409)
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
            self.frozen = set(plan["affected"])
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
        }

    def cancel_tasks(self, identifier, digest):
        """计划明确请求取消后仍等待执行真实结束"""
        with self.lock:
            plan = self._plan(identifier, digest)
            if plan["state"] != "preparing":
                raise Problem("请先准备变更。", 409)
            self.host.services["tasks"].cancel_owned(set(plan["affected"]))
            return self.progress(identifier)

    def window(self, identifier, generation):
        """窗口心跳同时取得冻结通知，过时代次不得自动刷新旧草稿"""
        with self.lock:
            self._generation(generation)
            if identifier not in self.windows:
                if self.frozen:
                    raise Problem("插件正在切换，请稍后重新协商。", 409)
                self.windows[identifier] = {"pending_plan": None, "acknowledged": False}
            window = self.windows[identifier]
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
            if window.get("connected") and time.time() - window["last_seen"] < 10:
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
        """提交前取消计划，解除冻结且保留已保存草稿"""
        with self.lock:
            plan = self._plan(identifier, digest)
            plan["state"] = "cancelled"
            self.save_plan(plan)
            self.frozen.clear()
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
            if progress["waiting_windows"] or progress["inflight"] or progress["tasks"]:
                raise Problem("仍有窗口草稿或请求未确认，变更尚未应用。", 409)
            if plan["mode"] == "host-restart":
                self.store.begin(plan)
                self.store.commit(
                    plan["selected"], self.host.generation + 1, self.package_lock(), plan["configs"]
                )
                self.maintenance = True
                plan["state"] = "restart-required"
                self.save_plan(plan)
                return {"generation": self.host.generation, "state": "restart-required"}
            self.store.begin(plan)
            self._switch(plan)
            return {"generation": self.host.generation, "state": "committed"}

    def _switch(self, plan):
        """候选注册失败时回收新作用域，旧代码兼容时恢复旧实例"""
        host = self.host
        old_selected, old_resolution = set(host.selected), host.resolution
        old_generation = host.generation
        old_configs, old_desired = host.configs, host.desired
        affected = set(plan["affected"])
        new_selected = set(plan["selected"])
        resolution = resolve(host.manifests, new_selected, host.required)
        self.maintenance = True
        try:
            for key in reversed(old_resolution.order):
                if key in affected:
                    for prepare in host.instances[key].before_deactivate:
                        prepare()
            for key in reversed(old_resolution.order):
                if key in affected:
                    host.instances[key].state = "draining"
                    host.instances[key].scope.close()
                    host.instances.pop(key)
            host.selected, host.resolution = new_selected, resolution
            host.configs, host.desired = deepcopy(plan["configs"]), set(new_selected)
            host.generation += 1
            if synchronize := host.bootstrap.get("synchronize_data"):
                synchronize(new_selected)
            for key in resolution.order:
                if key in affected:
                    host.activate_one(key)
                    if host.started:
                        for start in host.instances[key].starters:
                            start()
            if self.publish_routes:
                self.publish_routes()
            self.store.commit(new_selected, host.generation, self.package_lock(), host.configs)
            plan["state"] = "committed"
            self.save_plan(plan)
        except Exception as exc:
            self.store.failed(type(exc).__name__)
            try:
                for key in reversed(resolution.order):
                    if key in affected and key in host.instances:
                        host.instances[key].scope.close()
                        host.instances.pop(key)
                host.selected, host.resolution, host.generation = (
                    old_selected,
                    old_resolution,
                    old_generation,
                )
                host.configs, host.desired = old_configs, old_desired
                for key in old_resolution.order:
                    if key in affected and key not in host.instances:
                        host.activate_one(key)
                        if host.started:
                            for start in host.instances[key].starters:
                                start()
                if self.publish_routes:
                    self.publish_routes()
            except Exception as rollback:
                raise PluginError("插件切换及回滚失败，工作区保持维护状态") from rollback
            self.maintenance = False
            plan["state"] = "failed"
            self.save_plan(plan)
            raise Problem(f"插件切换失败，已恢复此前组合：{type(exc).__name__}", 409) from exc
        else:
            self.maintenance = False
            self.windows.clear()
        finally:
            if not self.maintenance:
                self.frozen.clear()
                self.pending_plan = None
                for window in self.windows.values():
                    window.update(pending_plan=None, acknowledged=False)
