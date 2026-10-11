"""备份历史、恢复确认、失败保留及本机文件边界"""

import json
import threading
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.infrastructure import storage
from resume_maker.infrastructure.backup_history import backup_path, list_backups
from resume_maker.infrastructure.database import Database
from resume_maker.infrastructure.storage import create_backup, instance_lock
from resume_maker.runtime.backup_restore import (
    apply_restore,
    plan_restore,
    read_restore,
    recover_missing_directory,
    rollback_restore,
    save_restore,
)

HEADERS = {"x-resume-token": "test-token"}


def test_history_distinguishes_sources_and_retains_legacy_and_bad_files(catalog):
    """来源由清单记录，旧文件不猜测，损坏文件仍能列出"""
    root = catalog.db.path.parent
    manual = create_backup(catalog.db, root)
    automatic = create_backup(catalog.db, root, kind="automatic", reason="plugin-change")
    legacy = root / "backups" / "legacy.zip"
    with ZipFile(manual) as source, ZipFile(legacy, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "backup.json":
                metadata = json.loads(data)
                metadata.pop("kind")
                metadata.pop("reason")
                data = json.dumps(metadata).encode()
            target.writestr(name, data)
    (root / "backups" / "broken.zip").write_bytes(b"synthetic corrupt archive")
    (root / "backups" / "unfinished.partial").write_bytes(b"not published")
    history = {item["id"]: item for item in list_backups(root)}
    assert len(history) == 4
    assert history[manual.name]["kind"] == "manual"
    assert history[automatic.name]["kind"] == "automatic"
    assert history[automatic.name]["reason"] == "plugin-change"
    assert history[legacy.name]["kind"] == "unknown"
    assert history[legacy.name]["restorable"]
    assert not history["broken.zip"]["restorable"]


@pytest.mark.parametrize(
    "identifier",
    ["../outside.zip", "..\\outside.zip", "C:outside.zip", "/outside.zip", ".hidden.zip"],
)
def test_backup_paths_reject_outside_files(tmp_path, identifier):
    """下载、删除及恢复共用路径限制，不能访问资料目录外文件"""
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"preserved")
    with pytest.raises(Problem, match="位置无效"):
        backup_path(tmp_path / "data", identifier)
    assert outside.read_bytes() == b"preserved"


def test_history_http_create_download_delete_and_auth(tmp_path):
    """手动备份进入历史，历史下载不新增备份，删除只移除选定 ZIP"""
    app = create_app(Config(data_dir=tmp_path / "data", token="test-token", profile="minimal"))
    with TestClient(app) as client:
        assert client.get("/api/backups").status_code == 401
        response = client.post("/api/backups", headers=HEADERS)
        assert response.status_code == 200, response.text
        items = client.get("/api/backups", headers=HEADERS).json()["items"]
        assert len(items) == 1 and items[0]["kind"] == "manual"
        identifier = items[0]["id"]
        assert (
            client.get(f"/api/backups/{identifier}/download", headers=HEADERS).content
            == response.content
        )
        assert len(client.get("/api/backups", headers=HEADERS).json()["items"]) == 1
        assert client.delete(f"/api/backups/{identifier}", headers=HEADERS).status_code == 200
        assert client.get("/api/backups", headers=HEADERS).json()["items"] == []
        assert client.get(f"/api/backups/{identifier}/download", headers=HEADERS).status_code == 404
        assert app.state.services.db.path.is_file()


def prepare_restore_plan(manager, archive):
    """合成官方重启回调，保留真实窗口确认及排空协议"""
    requested = []
    manager.host.bootstrap["request_restart"] = lambda: requested.append(True)
    plan = plan_restore(manager, archive.name, manager.host.generation)
    manager.prepare(plan["id"], plan["digest"])
    return plan, requested


def test_restore_waits_for_windows_and_protects_selected_backup(tmp_path):
    """未保存窗口不能被绕过，准备中的备份不能从历史删除"""
    root = tmp_path / "data"
    app = create_app(Config(data_dir=root, token="test-token", profile="minimal"))
    with TestClient(app) as client:
        manager = app.state.services.plugins
        manager.window("other", manager.host.generation)
        archive = create_backup(app.state.services.db, root)
        plan, requested = prepare_restore_plan(manager, archive)
        with pytest.raises(Problem, match="窗口"):
            manager.apply(plan["id"], plan["digest"])
        assert requested == []
        assert client.delete(f"/api/backups/{archive.name}", headers=HEADERS).status_code == 409
        assert (
            client.get("/api/backups", headers=HEADERS).json()["pending_restore"]["id"]
            == plan["id"]
        )
        assert not (root / "host-restore.json").exists()
        manager.acknowledge("other", plan["id"], manager.host.generation)
        manager.apply(plan["id"], plan["digest"])
        assert requested == [True]
        assert read_restore(root)["state"] == "prepared"


def test_restore_waits_for_requests_and_tasks(tmp_path):
    """在途写入及尚未结束的实际任务都阻止资料切换"""
    root = tmp_path / "data"
    app = create_app(Config(data_dir=root, profile="minimal"))
    with TestClient(app):
        manager = app.state.services.plugins
        archive = create_backup(app.state.services.db, root)
        plan, requested = prepare_restore_plan(manager, archive)
        manager.requests["sys.resume"] = 1
        with pytest.raises(Problem, match="尚未应用"):
            manager.apply(plan["id"], plan["digest"])
        manager.requests["sys.resume"] = 0
        tasks = manager.host.services["tasks"]
        original = tasks.active
        tasks.active = lambda *_: [{"id": "synthetic active task"}]
        try:
            with pytest.raises(Problem, match="尚未应用"):
                manager.apply(plan["id"], plan["digest"])
        finally:
            tasks.active = original
        assert requested == []
        manager.abort(plan["id"], plan["digest"])


def test_corrupt_restore_releases_freeze_and_keeps_current_data(tmp_path):
    """完整校验失败不发重启请求，原资料可继续编辑"""
    root = tmp_path / "data"
    app = create_app(Config(data_dir=root, profile="minimal"))
    with TestClient(app):
        db, manager = app.state.services.db, app.state.services.plugins
        db.set_setting("synthetic", "saved")
        archive = create_backup(db, root)
        with ZipFile(archive) as source:
            entries = [(name, source.read(name)) for name in source.namelist()]
        with ZipFile(archive, "w") as target:
            for name, data in entries:
                target.writestr(name, b"invalid database" if name == "resume.db" else data)
        plan, requested = prepare_restore_plan(manager, archive)
        with pytest.raises(Problem, match="校验失败"):
            manager.apply(plan["id"], plan["digest"])
        assert requested == [] and not manager.maintenance and not manager.frozen
        assert manager.pending_plan is None
        assert db.setting("synthetic") == "saved"
        db.set_setting("synthetic", "still editable")


def test_changed_backup_cannot_be_restored(tmp_path):
    """用户确认后替换目标文件会取消恢复，不能应用另一份资料"""
    root = tmp_path / "data"
    app = create_app(Config(data_dir=root, profile="minimal"))
    with TestClient(app):
        manager = app.state.services.plugins
        archive = create_backup(app.state.services.db, root)
        plan, requested = prepare_restore_plan(manager, archive)
        archive.write_bytes(b"changed")
        with pytest.raises(Problem, match="备份已变化"):
            manager.apply(plan["id"], plan["digest"])
        assert requested == [] and not manager.frozen


def test_supervised_restore_preserves_history_runtime_and_before_restore(tmp_path):
    """恢复回到目标资料，历史、本机运行文件及恢复前副本继续可用"""
    root = tmp_path / "data"
    app = create_app(Config(data_dir=root, profile="minimal"))
    with TestClient(app):
        db, manager = app.state.services.db, app.state.services.plugins
        db.set_setting("synthetic", "backup value")
        archive = create_backup(db, root)
        db.set_setting("synthetic", "current value")
        (root / "plugin-packages").mkdir()
        (root / "plugin-packages" / "local-only.txt").write_text("installed runtime")
        plan, requested = prepare_restore_plan(manager, archive)
        generation = manager.host.generation
        manager.apply(plan["id"], plan["digest"])
        assert requested == [True]
        record = read_restore(root)
        with instance_lock(root), pytest.raises(Problem, match="正在使用"):
            from resume_maker.infrastructure.storage import restore_backup

            restore_backup(archive, root)
    assert apply_restore(root, record)
    assert Database(root / "resume.db").setting("synthetic") == "backup value"
    assert (root / "plugin-packages" / "local-only.txt").read_text() == "installed runtime"
    assert len(list_backups(root)) == 2
    assert {item["reason"] for item in list_backups(root)} == {"manual", "before-restore"}
    previous = record["previous"]
    assert Database(Path(previous) / "resume.db").setting("synthetic") == "current value"
    assert json.loads((root / "plugins.json").read_text())["generation"] > generation
    save_restore(root, record, "committed", "备份已恢复。")
    restarted = create_app(Config(data_dir=root))
    with TestClient(restarted):
        assert restarted.state.services.db.setting("synthetic") == "backup value"


def test_restore_start_failure_returns_to_previous_directory(tmp_path):
    """恢复后无法启动时完整回退，故障资料单独保留供核对"""
    root = tmp_path / "data"
    app = create_app(Config(data_dir=root, profile="minimal"))
    with TestClient(app):
        db, manager = app.state.services.db, app.state.services.plugins
        db.set_setting("synthetic", "backup value")
        archive = create_backup(db, root)
        db.set_setting("synthetic", "current value")
        plan, _ = prepare_restore_plan(manager, archive)
        manager.apply(plan["id"], plan["digest"])
        record = read_restore(root)
    assert apply_restore(root, record)
    rollback_restore(root, record, "合成启动失败")
    assert Database(root / "resume.db").setting("synthetic") == "current value"
    assert read_restore(root)["state"] == "failed"
    assert len(list_backups(root)) == 2
    assert list(tmp_path.glob("data-failed-restore-*"))


def test_restore_endpoint_requires_supervision_and_current_generation(tmp_path):
    """恢复入口拒绝未受监督的服务及旧窗口，确认当前代次后才建立计划"""
    root = tmp_path / "data"
    app = create_app(Config(data_dir=root, profile="minimal", token="test-token"))
    with TestClient(app) as client:
        manager = app.state.services.plugins
        archive = create_backup(app.state.services.db, root)
        path = f"/api/backups/{archive.name}/restore-plan"
        assert not client.get("/api/backups", headers=HEADERS).json()["can_restore"]
        assert (
            client.post(
                path, headers=HEADERS, json={"generation": manager.host.generation}
            ).status_code
            == 409
        )
        manager.host.bootstrap["request_restart"] = lambda: None
        assert (
            client.post(
                path, headers=HEADERS, json={"generation": manager.host.generation + 1}
            ).status_code
            == 409
        )
        response = client.post(path, headers=HEADERS, json={"generation": manager.host.generation})
        assert response.status_code == 200, response.text
        plan = response.json()
        assert plan["mode"] == "backup-restore"
        assert plan["restore_backup"]["id"] == archive.name
        manager.abort(plan["id"], plan["digest"])


def test_interrupted_directory_switch_recovers_original_data(tmp_path):
    """旧目录已移走但新目录尚未发布时，重新启动不会建立空资料库"""
    root = tmp_path / "data"
    app = create_app(Config(data_dir=root, profile="minimal"))
    with TestClient(app):
        db, manager = app.state.services.db, app.state.services.plugins
        db.set_setting("synthetic", "saved")
        archive = create_backup(db, root)
        plan, _ = prepare_restore_plan(manager, archive)
        manager.apply(plan["id"], plan["digest"])
        record = read_restore(root)
    save_restore(root, record, "applying", "合成中断")
    root.rename(record["previous"])
    recover_missing_directory(root)
    assert Database(root / "resume.db").setting("synthetic") == "saved"
    assert read_restore(root)["state"] == "failed"


def test_http_backup_compression_allows_concurrent_draft_save(tmp_path, monkeypatch):
    """HTTP 备份压缩期间仍能提交编辑草稿，不持有宿主请求锁"""
    app = create_app(Config(data_dir=tmp_path / "data", profile="minimal", token="test-token"))
    finished, results = threading.Event(), []
    with TestClient(app) as client:

        def save():
            """在 ZIP 压缩尚未完成时提交一个真实草稿请求"""
            try:
                results.append(
                    client.put(
                        "/api/workspace-storage/rm.resume.v2.new",
                        headers=HEADERS,
                        json={"value": "synthetic draft", "version": 0},
                    ).status_code
                )
            finally:
                finished.set()

        worker = threading.Thread(target=save)

        class ConcurrentZip(ZipFile):
            """压缩开始后验证独立 HTTP 写入能够及时完成"""

            def __enter__(self):
                """备份线程不等待压缩结束才释放请求锁"""
                result = super().__enter__()
                worker.start()
                assert finished.wait(5)
                assert results == [200]
                return result

        try:
            with monkeypatch.context() as patch:
                patch.setattr(storage, "ZipFile", ConcurrentZip)
                response = client.post("/api/backups", headers=HEADERS)
                assert response.status_code == 200, response.text
        finally:
            if worker.ident:
                worker.join(5)
