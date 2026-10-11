"""真实候选进程、联合依赖、版本锁及兼容数据的自动代码回退"""

import json
import time

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.host_supervisor import apply_transition, read_transition, rollback
from resume_maker.infrastructure.database import Database
from resume_maker.runtime.graph import PluginError
from resume_maker.sdk.context import ServiceKey
from tests.support.plugins import bundle


def entry(store, path):
    """审查完整包并显式授予合成代码的执行信任"""
    inspection = store.inspect(path)
    return {
        "path": str(path),
        "digest": inspection["digest"],
        "trusted_modes": inspection["trust_modes"],
    }


def run_candidate(manager, plan):
    """保存窗口确认后的计划，等待真实独立解释器完成验证"""
    manager.prepare(plan["id"], plan["digest"])
    assert manager.apply(plan["id"], plan["digest"])["state"] == "validating"
    manager.upgrades.active.join(30)
    assert not manager.upgrades.active.is_alive()
    return manager.progress(plan["id"])


def test_new_candidate_health_failure_leaves_active_packages_and_data(tmp_path):
    """候选代码在独立 Host 健康检查失败，活动目录和正式资料保持原样"""
    path = tmp_path / "bad.rmp"
    bundle(
        path,
        extra={"contributes": {}, "provides": {}},
        artifacts_extra={
            "python/plugin.py": b'''def activate(context):
    """Register a deterministic synthetic failure"""
    def health():
        raise RuntimeError("synthetic candidate health failure")
    context.health(health)
'''
        },
    )
    app = create_app(Config(data_dir=tmp_path / "data", profile="minimal"))
    with TestClient(app):
        manager = app.state.services.plugins
        store = app.state.runtime.bootstrap["package_store"]
        app.state.services.db.set_setting("synthetic-preserved", {"value": 7})
        plan = manager.upgrades.plan(
            [entry(store, path)],
            manager.host.generation,
            sorted(manager.host.selected | {"community.example"}),
        )
        assert store.records() == {}
        outcome = run_candidate(manager, plan)
        assert outcome["state"] == "failed", outcome
        assert store.records() == {}
        assert not manager.maintenance
        assert app.state.services.db.setting("synthetic-preserved") == {"value": 7}
        assert not (tmp_path / "data" / "host-transition.json").exists()
        from resume_maker.infrastructure.backup_history import list_backups

        history = list_backups(tmp_path / "data")
        assert len(history) == 1
        assert history[0]["kind"] == "automatic" and history[0]["reason"] == "plugin-change"


def test_cohort_probe_commit_and_safe_code_rollback(tmp_path):
    """整组候选通过真实进程检查后才可切换，启动失败回退旧包且推进代次"""
    directory = tmp_path / "data"
    first, second = tmp_path / "one.rmp", tmp_path / "two.rmp"
    bundle(first)
    bundle(second, extra={"version": "2.0.0"})
    app = create_app(Config(data_dir=directory, profile="minimal"))
    with TestClient(app):
        manager = app.state.services.plugins
        store = app.state.runtime.bootstrap["package_store"]
        inspected = entry(store, first)
        manager.install(first, inspected["digest"], inspected["trusted_modes"])
        enable = manager.plan(
            sorted(manager.host.selected | {"community.example"}), manager.host.generation
        )
        manager.prepare(enable["id"], enable["digest"])
        manager.apply(enable["id"], enable["digest"])
        previous = store.records()
        store.pin("community.example", previous["community.example"]["digest"])
        with pytest.raises(PluginError, match="锁定"):
            manager.upgrades.plan([entry(store, second)], manager.host.generation)
        store.pin("community.example", None)
        plan = manager.upgrades.plan([entry(store, second)], manager.host.generation)
        result = run_candidate(manager, plan)
        assert result["state"] == "restart-required", result
        assert store.records() == previous
        assert manager.host.require(ServiceKey("example")) == "installed"
    transition = read_transition(directory)
    apply_transition(directory, transition)
    assert store.records()["community.example"]["version"] == "2.0.0"
    old_python = rollback(directory, transition, "synthetic startup failure")
    assert old_python and store.records() == previous
    restarted = create_app(Config(data_dir=directory))
    with TestClient(restarted):
        assert restarted.state.runtime.generation > plan["generation"] + 1
        assert restarted.state.runtime.require(ServiceKey("example")) == "installed"


def test_code_rollback_refuses_changed_data_version(tmp_path):
    """迁移已经改写资料版本时保留恢复点，不把旧代码重新开放给新数据"""
    directory = tmp_path / "data"
    db = Database(directory / "resume.db")
    from resume_maker.runtime.upgrades import data_signature, transition_digest

    signature = data_signature(db)
    transition = {
        "version": 1,
        "id": "synthetic",
        "plan": {"id": "synthetic"},
        "before": {},
        "after": {},
        "backup": "explicit-backup.zip",
        "data_signature": signature,
    }
    transition["digest"] = transition_digest(transition)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE plugin_data_catalog SET schema_version=2 WHERE plugin_id='sys.experience'"
        )
    with pytest.raises(Problem, match="不能自动回退"):
        rollback(directory, transition, "synthetic failure")
    assert read_transition(directory)["state"] == "recovery-required"


def test_multiple_packages_resolve_as_one_candidate(tmp_path):
    """单独更新消费者缺依赖，提供方和消费者联合试运行则完整通过"""
    provider, consumer = tmp_path / "provider.rmp", tmp_path / "consumer.rmp"
    bundle(provider, extra={"version": "2.0.0"})
    bundle(
        consumer,
        extra={
            "id": "community.consumer",
            "provides": {},
            "contributes": {},
            "plugins": {"community.example": ">=2.0.0 <3.0.0"},
        },
        artifacts_extra={
            "python/plugin.py": b'def activate(context):\n    """Synthetic consumer"""\n'
        },
    )
    app = create_app(Config(data_dir=tmp_path / "data", profile="minimal"))
    with TestClient(app):
        manager = app.state.services.plugins
        store = app.state.runtime.bootstrap["package_store"]
        selected = sorted(manager.host.selected | {"community.example", "community.consumer"})
        with pytest.raises(PluginError):
            manager.upgrades.plan([entry(store, consumer)], manager.host.generation, selected)
        plan = manager.upgrades.plan(
            [entry(store, consumer), entry(store, provider)], manager.host.generation, selected
        )
        result = run_candidate(manager, plan)
        assert result["state"] == "restart-required", result
        assert store.records() == {}


@pytest.mark.parametrize("fail_second", [False, True])
def test_cohort_data_migration_is_atomic_and_prevents_unsafe_rollback(tmp_path, fail_second):
    """整组资料只在全部迁移成功后发布，新增资料也阻止旧代码自动回退"""
    directory = tmp_path / "data"
    app = create_app(Config(data_dir=directory, profile="minimal"))
    with TestClient(app):
        manager = app.state.services.plugins
        store = app.state.runtime.bootstrap["package_store"]
        entries = []
        for owner in ["community.first", "community.second"]:
            package = tmp_path / (owner + ".rmp")
            bundle(
                package,
                extra={
                    "id": owner,
                    "provides": {},
                    "contributes": {},
                    "data": {
                        "schema_version": 1,
                        "reads": [1],
                        "writes": [1],
                        "settings": [owner + ":value"],
                        "migrations": ["migration.json"],
                    },
                },
                artifacts_extra={
                    "python/plugin.py": b'def activate(context):\n    """Synthetic no-op"""\n',
                    "migration.json": json.dumps(
                        {
                            "version": 1,
                            "from": 0,
                            "to": 1,
                            "settings": [{"key": owner + ":value", "value": 7}],
                        }
                    ).encode(),
                },
            )
            entries.append(entry(store, package))
        plan = manager.upgrades.plan(
            entries,
            manager.host.generation,
            sorted(manager.host.selected | {"community.first", "community.second"}),
        )
        assert len(plan["data_intents"]) == 2
        result = run_candidate(manager, plan)
        assert result["state"] == "restart-required", result
        assert app.state.services.db.setting("community.first:value") is None
    transition = read_transition(directory)
    if fail_second:
        # 试运行通过后模拟正式切换时第二个迁移失败，第一项副本写入不能泄漏
        transition["plan"]["data_intents"][1]["to"] = 99
        with pytest.raises(Problem, match="变化"):
            apply_transition(directory, transition)
        db = Database(directory / "resume.db", plugins=[])
        assert db.setting("community.first:value") is None
        assert store.records() == {}
        assert rollback(directory, transition, "合成正式迁移失败")
    else:
        apply_transition(directory, transition)
        db = Database(directory / "resume.db", plugins=[])
        assert db.setting("community.first:value") == 7
        assert db.setting("community.second:value") == 7
        with pytest.raises(Problem, match="不能自动回退"):
            rollback(directory, transition, "合成启动失败")
        from pathlib import Path

        from resume_maker.infrastructure.storage import restore_backup

        # 各类维护目录属于本实例，显式恢复仍应保留整份故障现场
        for name in ["plugin-downloads", "plugin-trials", "plugin-migrations"]:
            (directory / name).mkdir(exist_ok=True)
        previous = restore_backup(Path(transition["backup"]), directory)
        assert (previous / "host-transition.json").is_file()
        restored = Database(directory / "resume.db", plugins=[])
        assert restored.setting("community.first:value") is None
        assert not (directory / "host-transition.json").exists()
        assert not restored.one("SELECT name FROM sqlite_master WHERE name='templates'")


def test_namespaced_settings_initialize_without_artificial_sql_migration(tmp_path):
    """只有命名空间设置的初次安装登记资料目录册，无需发布空 SQL 文件"""
    package = tmp_path / "settings.rmp"
    bundle(package, extra={"data": {"settings": ["community.example:value"]}})
    directory = tmp_path / "data"
    app = create_app(Config(data_dir=directory, profile="minimal"))
    with TestClient(app):
        manager = app.state.services.plugins
        plan = manager.upgrades.plan(
            [entry(app.state.runtime.bootstrap["package_store"], package)],
            manager.host.generation,
            sorted(manager.host.selected | {"community.example"}),
        )
        assert plan["data_intents"][0]["initialize"]
        assert run_candidate(manager, plan)["state"] == "restart-required"
    apply_transition(directory, read_transition(directory))
    with TestClient(create_app(Config(data_dir=directory))) as client:
        assert client.app.state.runtime.require(ServiceKey("example")) == "installed"


def test_declared_restart_toggle_uses_the_same_trial_and_supervisor_protocol(tmp_path):
    """仅启用已有重启型插件也先试运行，不把配置直接提交为成功"""
    package = tmp_path / "restart.rmp"
    bundle(package, extra={"lifecycle": {"toggle": "host-restart"}})
    directory = tmp_path / "data"
    app = create_app(Config(data_dir=directory, profile="minimal"))
    with TestClient(app):
        manager = app.state.services.plugins
        store = app.state.runtime.bootstrap["package_store"]
        checked = entry(store, package)
        manager.install(package, checked["digest"], checked["trusted_modes"])
        plan = manager.plan(
            sorted(manager.host.selected | {"community.example"}), manager.host.generation
        )
        assert plan["mode"] == "host-restart" and plan["package_updates"] == {}
        assert set(plan["affected"]) == set(plan["selected"])
        assert run_candidate(manager, plan)["state"] == "restart-required"
        assert "community.example" not in manager.store.read()["selected"]
    transition = read_transition(directory)
    apply_transition(directory, transition)
    with TestClient(create_app(Config(data_dir=directory))) as client:
        assert client.app.state.runtime.require(ServiceKey("example")) == "installed"


def test_new_instance_can_be_probed_before_it_exists_in_active_host(tmp_path):
    """候选重启按新实例定义解析依赖，不能只查旧宿主的实例表"""
    package = tmp_path / "instance.rmp"
    bundle(
        package,
        extra={
            "instances": {"multiple": True},
            "provides": {},
            "contributes": {},
            "lifecycle": {"toggle": "host-restart"},
        },
        artifacts_extra={"python/plugin.py": b'def activate(context):\n    """No-op"""\n'},
    )
    directory = tmp_path / "data"
    app = create_app(Config(data_dir=directory, profile="minimal"))
    with TestClient(app):
        manager = app.state.services.plugins
        store = app.state.runtime.bootstrap["package_store"]
        checked = entry(store, package)
        manager.install(package, checked["digest"], checked["trusted_modes"])
        plan = manager.plan(
            sorted(manager.host.selected | {"community.second"}),
            manager.host.generation,
            instances=[{"id": "community.second", "plugin": "community.example"}],
        )
        assert run_candidate(manager, plan)["state"] == "restart-required"
    apply_transition(directory, read_transition(directory))
    with TestClient(create_app(Config(data_dir=directory))) as client:
        assert "community.second" in client.app.state.runtime.selected


def test_cancelling_real_candidate_waits_for_process_exit(tmp_path):
    """取消真正运行的候选进程后才解除维护状态，正式安装索引保持原样"""
    package = tmp_path / "slow.rmp"
    marker = tmp_path / "started.txt"
    code = (
        "from pathlib import Path\nimport time\ndef activate(context):\n"
        f'    Path({str(marker)!r}).write_text("started")\n    time.sleep(90)\n'
    )
    bundle(
        package,
        extra={"provides": {}, "contributes": {}},
        artifacts_extra={"python/plugin.py": code.encode()},
    )
    app = create_app(Config(data_dir=tmp_path / "data", profile="minimal"))
    with TestClient(app):
        manager = app.state.services.plugins
        store = app.state.runtime.bootstrap["package_store"]
        plan = manager.upgrades.plan(
            [entry(store, package)],
            manager.host.generation,
            sorted(manager.host.selected | {"community.example"}),
        )
        manager.prepare(plan["id"], plan["digest"])
        manager.apply(plan["id"], plan["digest"])
        deadline = time.monotonic() + 20
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists()
        manager.upgrades.cancel(plan["id"])
        manager.upgrades.active.join(15)
        assert not manager.upgrades.active.is_alive()
        assert manager.progress(plan["id"])["state"] == "cancelled"
        assert not manager.maintenance and store.records() == {}


def test_supervisor_restarts_old_host_after_candidate_boot_failure(tmp_path, monkeypatch):
    """真实监督器切换时新宿主失败，旧宿主自动重启并重新提供业务接口"""
    import re
    import socket
    import subprocess
    import sys
    from urllib.request import Request, urlopen

    directory = tmp_path / "data"
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        '<html><head><meta name="resume-token" content="__RESUME_TOKEN__"></head></html>',
        encoding="utf-8",
    )
    monkeypatch.setenv("RESUME_MAKER_FRONTEND_DIR", str(frontend))
    package = tmp_path / "bad-boot.rmp"
    bundle(
        package,
        extra={"provides": {}, "contributes": {}},
        artifacts_extra={
            "python/plugin.py": b'''from pathlib import Path
def activate(context):
    """Fail only after leaving the trial copy"""
    if "plugin-trials" not in Path.cwd().parts:
        raise RuntimeError("synthetic final host failure")
''',
        },
    )
    app = create_app(Config(data_dir=directory, profile="minimal"))
    with TestClient(app):
        manager = app.state.services.plugins
        store = app.state.runtime.bootstrap["package_store"]
        plan = manager.upgrades.plan(
            [entry(store, package)],
            manager.host.generation,
            sorted(manager.host.selected | {"community.example"}),
        )
        assert run_candidate(manager, plan)["state"] == "restart-required"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    with (tmp_path / "supervisor.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "resume_maker",
                "--data-dir",
                str(directory),
                "--port",
                str(port),
                "--no-browser",
                "--no-env-file",
            ],
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                assert process.poll() is None, (tmp_path / "supervisor.log").read_text()
                if read_transition(directory)["state"] == "rolled-back":
                    try:
                        with urlopen(url + "/api/health", timeout=1) as response:
                            assert json.load(response)["status"] == "ok"
                            break
                    except OSError:
                        pass
                time.sleep(0.1)
            else:
                pytest.fail("监督器未在期限内恢复旧宿主")
            assert store.records() == {}
            with urlopen(url, timeout=2) as response:
                html = response.read().decode()
            token = re.search(r'name="resume-token" content="([^"]+)"', html)[1]
            headers = {"x-resume-token": token}
            with urlopen(Request(url + "/api/state", headers=headers), timeout=2) as response:
                assert "projects" in json.load(response)
            with urlopen(
                Request(url + "/api/shutdown", method="POST", headers=headers), timeout=2
            ) as response:
                assert json.load(response)["ok"]
            assert process.wait(timeout=10) == 0
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


def test_supervisor_retains_explicit_configuration_but_trial_does_not_inherit_credentials(
    monkeypatch,
):
    """正式启动保持自定义配置和凭据兼容，试运行不继承模型环境密钥"""
    from resume_maker.host_supervisor import host_environment
    from resume_maker.runtime.upgrades import process_environment

    monkeypatch.setenv("SYNTHETIC_PROVIDER_KEY", "synthetic-credential")
    monkeypatch.setenv("CODEX_HOME", "synthetic-custom-cli-home")
    assert host_environment()["SYNTHETIC_PROVIDER_KEY"] == "synthetic-credential"
    assert host_environment()["CODEX_HOME"] == "synthetic-custom-cli-home"
    assert "SYNTHETIC_PROVIDER_KEY" not in process_environment()
    assert "CODEX_HOME" not in process_environment()
