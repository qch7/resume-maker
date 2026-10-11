"""联合候选升级协调，活动包索引在独立 Host 通过验证前保持不变"""

import sqlite3
import sys
import threading
from contextlib import closing
from copy import deepcopy
from pathlib import Path

from resume_maker.core.errors import Problem
from resume_maker.core.process_environment import EnvironmentPolicy
from resume_maker.core.process_environment import process_environment as inherited_environment
from resume_maker.infrastructure.data_maintenance import (
    DataMaintenance,
    apply_intents,
    migration_intent,
)
from resume_maker.infrastructure.database import Database
from resume_maker.infrastructure.storage import create_backup, restore_backup
from resume_maker.runtime.state import StateStore, fingerprint


def process_environment():
    """候选进程只继承基础运行路径，不复制模型凭据"""
    return inherited_environment(EnvironmentPolicy.CANDIDATE)


class Upgrades:
    """候选试运行和正式重启使用同一计划，失败保留旧代码及用户资料"""

    def __init__(self, manager):
        """只有宿主停止后监督器才提交包索引及新代次"""
        self.manager = manager
        self.active = None
        self.cancelled = threading.Event()

    def plan(
        self, entries, generation, selected=None, *, instances=None, configs=None, config_edits=()
    ):
        """完整暂存所有候选，再联合求解依赖，不逐包改写活动索引"""
        manager, host = self.manager, self.manager.host
        with manager.lock:
            manager._generation(generation)
            if manager.pending_plan or manager.maintenance:
                raise Problem("请先完成当前插件变更。", 409)
            updates, seen, intents = {}, set(), []
            packages = host.bootstrap["package_store"]
            for entry in entries:
                result = packages.install(
                    Path(entry["path"]), entry["digest"], set(entry["trusted_modes"]), commit=False
                )
                if result["id"] in seen:
                    raise Problem("一次联合计划不能包含同一插件的多个版本。", 409)
                seen.add(result["id"])
                updates[result["id"]] = result["record"]
                manifest, location = packages._discover_one(result["id"], result["record"])
                if manifest.data:
                    data_plan = DataMaintenance(
                        host.services["db"], host.bootstrap["config"].data_dir
                    ).plan(manifest, location)
                    if data_plan["steps"] or data_plan["initialize"]:
                        intents.append(migration_intent(data_plan))
            if not updates:
                raise Problem("请至少选择一个候选插件包。")
            return manager.plan(
                selected if selected is not None else sorted(host.selected),
                generation,
                instances=instances,
                configs=configs,
                config_edits=config_edits,
                package_updates=updates,
                data_intents=intents,
            )

    def start(self, plan):
        """窗口和业务排空后开始独立候选验证，管理通道持续可查询"""
        manager = self.manager
        if self.active and self.active.is_alive():
            raise Problem("候选验证仍在进行。", 409)
        self.cancelled.clear()
        manager.maintenance = True
        plan.update(state="validating", stage="backup", message="正在保存候选试运行所需的资料快照")
        manager.save_plan(plan)
        self.active = threading.Thread(target=self._run, args=(plan,), daemon=True)
        self.active.start()
        return {"generation": manager.host.generation, "state": "validating", "id": plan["id"]}

    def _stage(self, plan, stage, message):
        """每个实际步骤独立落盘，不把耗时估算显示成下载或安装百分比"""
        with self.manager.lock:
            if self.cancelled.is_set():
                raise Problem("候选验证已取消。", 409)
            plan.update(stage=stage, message=message)
            self.manager.save_plan(plan)

    def _run(self, plan):
        """使用备份副本和独立解释器启动候选，正式资料不交给试运行修改"""
        manager, host = self.manager, self.manager.host
        directory = host.bootstrap["config"].data_dir
        writer = StateStore(directory)
        try:
            backup = create_backup(
                host.services["db"], directory, kind="automatic", reason="plugin-change"
            )
            trial = directory / "plugin-trials" / plan["id"]
            restore_backup(backup, trial)
            packages = host.bootstrap["package_store"]
            records = {**plan["packages_before"], **plan["package_updates"]}
            if plan.get("data_intents"):
                self._stage(plan, "migration-trial", "正在资料副本中验证已审查的迁移步骤")
                with (
                    host.services["db"].connect() as source,
                    closing(sqlite3.connect(trial / "resume.db")) as target,
                ):
                    source.backup(target)
                trial_db = Database(trial / "resume.db", plugins=[])
                apply_intents(trial_db, trial, plan["data_intents"], packages, records)
            definitions = dict(host.definitions)
            for owner, record in plan["package_updates"].items():
                definitions[owner], _ = packages._discover_one(owner, record)
            instances = {item["id"]: item["plugin"] for item in plan.get("instances", [])}
            selected_definitions = tuple(
                definitions[instances.get(key, key)] for key in plan["selected"]
            )
            python = sys.executable
            environments_before = host.bootstrap["environment_store"].records()
            environments_after = deepcopy(environments_before)
            environment_store = host.bootstrap["environment_store"]
            host_locks = []
            for manifest in selected_definitions:
                if not manifest.environment_lock or manifest.id not in records:
                    continue
                _, location = packages._discover_one(manifest.id, records[manifest.id])
                if "host" in manifest.entrypoints:
                    host_locks.append((manifest, location))
                elif manifest.id in plan["package_updates"]:
                    self._stage(plan, "environment", f"正在准备 {manifest.id} 的固定依赖环境")
                    environments_after[manifest.id] = environment_store.prepare(
                        manifest,
                        location,
                        host.services["execution"],
                        host.services["sandbox"],
                        selected_definitions,
                        cancelled=self.cancelled,
                        commit=False,
                    )
            if host_locks:
                self._stage(plan, "environment", "正在检查并准备整组 Host 的固定依赖")
                prepared = environment_store.prepare_host(
                    host_locks,
                    host.services["execution"],
                    host.services["sandbox"],
                    selected_definitions,
                    cancelled=self.cancelled,
                )
                python = prepared["python"]
                environments_after["host.cohort"] = prepared
            self._stage(plan, "health", "正在独立进程中验证整套插件及健康检查")
            trial_state = StateStore(trial)
            trial_state.commit(
                plan["selected"],
                plan["generation"] + 1,
                {},
                plan["configs"],
                instances=plan["instances"],
                config_layers=plan["configuration"]["layers"],
            )
            spec = {
                "data_dir": str(trial),
                "package_root": str(directory),
                "packages": records,
                "environments": environments_after,
                "selected": plan["selected"],
                "generation": plan["generation"] + 1,
            }
            spec_path = trial.parent / (plan["id"] + ".json")
            writer.write(spec_path, spec)
            command = [
                str(python),
                "-I",
                "-X",
                "utf8",
                "-m",
                "resume_maker.candidate_host",
                str(spec_path),
            ]
            environment = process_environment()
            grant = host.services["sandbox"].authorize(
                "sys.plugins",
                "plugin.candidate",
                host.generation,
                ["process_cleanup"],
                command=command,
                cwd=trial,
                env=environment,
                materials=[spec_path],
            )
            host.services["execution"].execute(
                grant,
                command,
                cwd=trial,
                env=environment,
                timeout=manager.policy.candidate_timeout_seconds,
                cancelled=self.cancelled,
            )
            self._stage(plan, "restart", "候选健康检查通过，等待监督器切换宿主")
            with manager.lock:
                if self.cancelled.is_set():
                    raise Problem("候选验证已取消。", 409)
                if packages.records() != plan["packages_before"] or packages.pins() != plan["pins"]:
                    raise Problem("验证期间安装目录发生变化，旧组合继续运行。", 409)
                transition = {
                    "version": 1,
                    "id": plan["id"],
                    "state": "prepared",
                    "plan": deepcopy(plan),
                    "before": {
                        "packages": plan["packages_before"],
                        "configuration": manager.store.read(),
                        "environments": environments_before,
                        "python": sys.executable,
                    },
                    "after": {
                        "packages": records,
                        "python": str(python),
                        "environments": environments_after,
                    },
                    "backup": str(backup),
                    "data_signature": data_signature(host.services["db"]),
                }
                transition["digest"] = transition_digest(transition)
                writer.write(directory / "host-transition.json", transition)
                plan.update(state="restart-required", stage="restart")
                manager.save_plan(plan)
                if restart := host.bootstrap.get("request_restart"):
                    restart()
        except Exception as exc:
            with manager.lock:
                plan.update(
                    state="cancelled" if self.cancelled.is_set() else "failed",
                    stage="finished",
                    message=str(exc) if isinstance(exc, Problem) else type(exc).__name__,
                )
                manager.save_plan(plan)
                manager.maintenance = False
                manager.frozen.clear()
                with host.scope_lock:
                    host.frozen_scopes.clear()
                manager.pending_plan = None
                for window in manager.windows.values():
                    window.update(pending_plan=None, acknowledged=False)

    def cancel(self, identifier):
        """只取消仍在验证的候选，正式重启请求不会被误当作普通取消"""
        with self.manager.lock:
            plan = self.manager.plans.get(identifier)
            if not plan or plan["state"] != "validating":
                raise Problem("该候选已结束验证，无法取消。", 409)
            self.cancelled.set()
            plan["stage"] = "cancelling"
            self.manager.save_plan(plan)
            return deepcopy(plan)

    def close(self):
        """停止时等待本轮候选线程和它拥有的进程真实结束"""
        self.cancelled.set()
        if self.active and self.active is not threading.current_thread():
            self.active.join(15)
            if self.active.is_alive():
                raise Problem("候选进程尚未结束，不能释放依赖。", 409)


def data_signature(db):
    """代码回退只允许使用相同的数据结构和插件资料版本"""
    return {
        "schema": db.one("PRAGMA user_version")["user_version"],
        "plugins": {
            row["plugin_id"]: row["schema_version"]
            for row in db.all(
                "SELECT plugin_id,schema_version FROM plugin_data_catalog ORDER BY plugin_id"
            )
        },
    }


def transition_digest(value):
    """固定经确认的切换材料，状态和诊断更新不改变授权内容"""
    return fingerprint(
        {
            key: value[key]
            for key in (
                "version",
                "id",
                "plan",
                "before",
                "after",
                "backup",
                "data_signature",
            )
        }
    )
