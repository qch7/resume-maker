"""稳定启动监督器，候选宿主通过观察期前不开放业务写入"""

import hashlib
import json
import sqlite3
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

from resume_maker.core.errors import Problem
from resume_maker.core.process_environment import EnvironmentPolicy, process_environment
from resume_maker.infrastructure.data_maintenance import apply_intents
from resume_maker.infrastructure.database import Database
from resume_maker.infrastructure.execution import Execution, Sandbox
from resume_maker.infrastructure.storage import instance_lock
from resume_maker.integrations.providers.process import execute
from resume_maker.integrations.providers.sandbox import LocalSandbox
from resume_maker.plugins.discovery import discover
from resume_maker.runtime.packages import PackageStore
from resume_maker.runtime.state import StateStore
from resume_maker.runtime.upgrades import transition_digest


def read_transition(directory):
    """切换记录可跨监督器中断恢复，内容改变时停止自动执行"""
    path = directory / "host-transition.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value["digest"] != transition_digest(value):
        raise Problem("宿主切换记录摘要不匹配，请检查本机维护记录。", 409)
    return value


def schema_compatible(directory, expected, *, strict=False):
    """只有原有资料版本完全兼容时才自动回退代码，不自动恢复用户数据库"""
    with closing(
        sqlite3.connect((directory / "resume.db").as_uri() + "?mode=ro", uri=True)
    ) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        current = dict(conn.execute("SELECT plugin_id,schema_version FROM plugin_data_catalog"))
    return (
        (not strict or current == expected["plugins"])
        and version == expected["schema"]
        and all(current.get(key) == value for key, value in expected["plugins"].items())
    )


def save_transition(directory, transition, state, message=None):
    """实际阶段写入切换记录及原计划，响应丢失后查询同一身份"""
    writer = StateStore(directory)
    transition["state"] = state
    if message:
        transition["message"] = message
    writer.write(directory / "host-transition.json", transition)
    plan = {**transition["plan"], "state": state, "stage": state, "message": message or state}
    writer.save_plan(plan)


def save_runtime(directory, python):
    """解释器引用先于提交标记发布，中断回退同时恢复这份引用"""
    StateStore(directory).write(
        directory / "host-runtime.json",
        {"python": str(python), "sha256": hashlib.sha256(Path(python).read_bytes()).hexdigest()},
    )


def host_environment():
    """正式宿主保留供应商连接输入，启动字段由监督器参数固定"""
    return process_environment(EnvironmentPolicy.HOST)


def host_command(python, directory, args, *, first, candidate):
    """固定本次目录和端口，重启沿用已保存的插件选择并禁用文件重读"""
    command = [
        str(python),
        "-I",
        "-X",
        "utf8",
        "-m",
        "resume_maker",
        "--host-child",
        "--no-env-file",
        "--data-dir",
        str(directory),
        "--port",
        str(args.port),
        "--no-browser" if args.no_browser or not first else "--browser",
    ]
    if frontend := getattr(args, "frontend_dir", None):
        command.extend(["--frontend-dir", str(frontend)])
    if first and not candidate:
        if args.profile:
            command.extend(["--profile", args.profile])
        if args.plugin_config:
            command.extend(["--plugin-config", str(args.plugin_config.resolve())])
    return command


def apply_transition(directory, transition):
    """停止旧进程并取得实例锁后才发布整组包和新的配置代次"""
    writer = StateStore(directory)
    packages = PackageStore(directory, set(discover()[0]))
    if packages.records() != transition["before"]["packages"]:
        raise Problem("正式安装目录已变化，候选计划失效。", 409)
    if packages.pins() != transition["plan"]["pins"]:
        raise Problem("插件版本锁已变化，候选计划失效。", 409)
    if not schema_compatible(
        directory, transition["data_signature"], strict=bool(transition["plan"].get("data_intents"))
    ):
        raise Problem("资料结构在验证后变化，必须重新检查候选。", 409)
    for owner, record in transition["after"]["packages"].items():
        packages._discover_one(owner, record)
    plan = transition["plan"]
    save_transition(directory, transition, "applying")
    if plan.get("data_intents"):
        migrate_cohort(directory, transition, packages)
    writer.write(packages.index, {"version": 1, "packages": transition["after"]["packages"]})
    writer.write(
        directory / "plugin-environments.json",
        {"version": 1, "environments": transition["after"]["environments"]},
    )
    writer.commit(
        plan["selected"],
        plan["generation"] + 1,
        {},
        plan["configs"],
        instances=plan["instances"],
        config_layers=plan["configuration"]["layers"],
    )
    save_transition(directory, transition, "booting", "新宿主正在启动和执行健康观察")


def migrate_cohort(directory, transition, packages):
    """在独立数据库完成整组迁移，全部成功后才替换正式库"""
    path = directory / "plugin-migrations" / transition["id"] / "resume.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    original = Database(directory / "resume.db", plugins=[])
    with original.connect() as source, closing(sqlite3.connect(path)) as target:
        source.backup(target)
    candidate = Database(path, plugins=[])
    reports = apply_intents(
        candidate,
        directory,
        transition["plan"]["data_intents"],
        packages,
        transition["after"]["packages"],
    )
    with candidate.connect() as conn:
        if (
            conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            or conn.execute("PRAGMA foreign_key_check").fetchone()
        ):
            raise Problem("整组迁移后的资料校验失败，正式资料保持原样。", 409)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
    with original.connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    StateStore(directory).write(
        path.parent / "operation.json",
        {
            "state": "prepared",
            "reports": reports,
            "backup": transition["backup"],
            "automatic_code_rollback": False,
        },
    )
    path.replace(original.path)
    StateStore(directory).write(
        path.parent / "operation.json",
        {
            "state": "committed",
            "reports": reports,
            "backup": transition["backup"],
            "automatic_code_rollback": False,
        },
    )


def rollback(directory, transition, reason):
    """仅回退代码、环境和配置，遇到资料迁移保留维护状态及完整恢复点"""
    if not schema_compatible(
        directory,
        transition["data_signature"],
        strict=bool(transition["plan"].get("data_intents")),
    ):
        save_transition(
            directory,
            transition,
            "recovery-required",
            "数据结构已变化，已停止自动代码回退；请核对迁移记录及完整备份。",
        )
        raise Problem("数据结构已变化，不能自动回退旧代码。完整备份：" + transition["backup"], 409)
    writer = StateStore(directory)
    before = transition["before"]
    writer.write(directory / "plugin-packages.json", {"version": 1, "packages": before["packages"]})
    writer.write(
        directory / "plugin-environments.json",
        {"version": 1, "environments": before["environments"]},
    )
    current = writer.read()
    saved = {
        **before["configuration"],
        "generation": max(current["generation"], transition["plan"]["generation"]) + 1,
    }
    writer.write(writer.path, saved)
    save_runtime(directory, before["python"])
    save_transition(directory, transition, "rolled-back", reason)
    return before["python"]


def supervise(config, args):
    """监督器保持稳定解释器，实际应用总在可替换且受控的子进程运行"""
    directory = config.data_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with instance_lock(directory.parent / (directory.name + ".supervisor")):
        execution = Execution(execute)
        sandbox = Sandbox(execution, LocalSandbox())
        python = sys.executable
        active_path = directory / "host-runtime.json"
        if active_path.exists():
            active = json.loads(active_path.read_text(encoding="utf-8"))
            python = active["python"]
            if hashlib.sha256(Path(python).read_bytes()).hexdigest() != active["sha256"]:
                raise Problem("保存的宿主解释器已变化，请重新核验安装环境。", 409)
        first = True
        while True:
            transition = read_transition(directory)
            if transition and transition["state"] in {"applying", "booting"}:
                with instance_lock(directory):
                    python = rollback(directory, transition, "上次候选启动中断，已恢复旧代码环境。")
            if transition and transition["state"] == "recovery-required":
                raise Problem(transition["message"], 409)
            candidate = transition if transition and transition["state"] == "prepared" else None
            if candidate:
                with instance_lock(directory):
                    try:
                        apply_transition(directory, candidate)
                    except Exception as exc:
                        python = rollback(
                            directory, candidate, "候选切换失败，已恢复旧代码环境：" + str(exc)
                        )
                        continue
                python = candidate["after"]["python"]
            command = host_command(python, directory, args, first=first, candidate=candidate)
            first = False
            cancelled, completed = threading.Event(), threading.Event()
            state = {"started": time.monotonic(), "health_since": None, "committed": False}
            failure = None

            def event(value, state=state, candidate=candidate, python=python):
                """候选持续健康且尚未开放写入时提交，普通服务消息不充当健康证明"""
                if value.get("event") != "host-health":
                    return
                if state["health_since"] is None and not candidate:
                    print(f"Resume Maker is ready at http://127.0.0.1:{args.port}", flush=True)
                state["health_since"] = state["health_since"] or time.monotonic()
                if candidate and value.get("transition") != candidate["id"]:
                    raise Problem("候选宿主返回的维护身份不匹配。", 409)
                if (
                    candidate
                    and not state["committed"]
                    and time.monotonic() - state["health_since"] >= 3
                ):
                    save_runtime(directory, python)
                    save_transition(
                        directory, candidate, "committed", "新宿主健康检查通过，整组升级已生效。"
                    )
                    state["committed"] = True

            def deadline(state=state, completed=completed, cancelled=cancelled):
                """启动没有就绪消息时取消本次进程，正常运行不设置服务寿命上限"""
                while not completed.wait(0.2):
                    if state["health_since"] is None and time.monotonic() - state["started"] > 120:
                        cancelled.set()
                        return

            monitor = threading.Thread(target=deadline, daemon=True)
            monitor.start()
            environment = host_environment()
            grant = sandbox.authorize(
                "sys.plugins",
                "host.supervisor",
                1,
                ["process_cleanup"],
                command=command,
                cwd=directory,
                env=environment,
            )
            try:
                execution.execute(
                    grant,
                    command,
                    cwd=directory,
                    env=environment,
                    timeout=10**10,
                    cancelled=cancelled,
                    event=event,
                )
            except Exception as exc:
                failure = str(exc)
            finally:
                completed.set()
                monitor.join()
            if candidate and not state["committed"]:
                with instance_lock(directory):
                    python = rollback(
                        directory,
                        candidate,
                        "新宿主启动失败，已恢复旧代码环境：" + (failure or "提前结束"),
                    )
                continue
            next_transition = read_transition(directory)
            if next_transition and next_transition["state"] == "prepared":
                continue
            if failure:
                raise Problem("宿主已停止：" + failure, 500)
            return


def watch_host(app, config, server):
    """子宿主持续检查候选健康，监督器提交之前保持业务维护状态"""
    host, manager = app.state.runtime, app.state.runtime.bootstrap["plugin_manager"]
    transition = read_transition(config.data_dir)
    candidate = transition if transition and transition["state"] == "booting" else None
    if candidate:
        manager.maintenance = True
    host.bootstrap["request_restart"] = lambda: setattr(server, "should_exit", True)
    stopped = threading.Event()

    def observe():
        """在启动生命周期完成后报告健康，异常使当前候选退出并交由监督器处理"""
        while not stopped.is_set():
            try:
                host.check_health()
                if candidate and host.selected != set(candidate["plan"]["selected"]):
                    raise Problem("候选有未能启动的能力。", 409)
                print(
                    json.dumps(
                        {
                            "event": "host-health",
                            "transition": candidate["id"] if candidate else None,
                        }
                    ),
                    flush=True,
                )
                if candidate:
                    current = read_transition(config.data_dir)
                    if current["state"] == "committed":
                        manager.maintenance = False
                        return
                else:
                    return
            except Exception:
                server.should_exit = True
                return
            stopped.wait(0.5)

    def ready():
        """宿主启动成功后才创建观察线程，启动异常不能发送就绪消息"""
        threading.Thread(target=observe, daemon=True).start()

    host.bootstrap["on_ready"] = ready
    return stopped
