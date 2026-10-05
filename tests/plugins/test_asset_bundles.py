"""不可变原件、原子引用和统一资源恢复的用户行为验收"""

from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.infrastructure.assets import Assets
from resume_maker.infrastructure.database import Database
from resume_maker.infrastructure.storage import create_backup, restore_backup
from resume_maker.plugin_packages.ext_honors.services.honors import Honors
from tests.support.honors import certificate_bytes


def test_certificate_backup_restores_without_optional_plugin(tmp_path):
    """证书只发布统一资源，最小组合和缺插件恢复仍保留完整原件"""
    directory = tmp_path / "data"
    db = Database(directory / "resume.db")
    raw = certificate_bytes()
    assets = Assets(db, directory)
    item = Honors(db, directory, None, assets=assets).upload(raw, "certificate.png")
    assert not (directory / "honors" / item["id"]).exists()
    assert assets.read_file(f"honors/{item['id']}", "original.png") == raw
    backup = create_backup(db, directory)
    with ZipFile(backup) as archive:
        assert not any(name.startswith("honors/") for name in archive.namelist())
    restored = tmp_path / "restored"
    restore_backup(backup, restored)
    app = create_app(Config(data_dir=restored, profile="minimal", token="test"))
    with TestClient(app, headers={"x-resume-token": "test"}) as client:
        assert client.get("/api/honors").status_code == 404
        assert app.state.services.assets.read_file(f"honors/{item['id']}", "original.png") == raw
        assert client.post("/api/backups").status_code == 200


def test_failed_bundle_publish_preserves_previous_files_and_references(tmp_path):
    """业务事务失败时原件和索引完整保留，替换成功后旧文件仍受在途租约保护"""
    assets = Assets(Database(tmp_path / "resume.db"), tmp_path)
    first = assets.stage_bundle("example", {"original": b"first", "copy": b"first"})
    assert first["original"]["id"] == first["copy"]["id"]
    with assets.db.transaction() as conn:
        assets.publish_bundle(conn, "example", "examples/one", first)
    second = assets.stage_bundle("example", {"original": b"second"})
    with pytest.raises(RuntimeError), assets.db.transaction() as conn:
        assets.publish_bundle(conn, "example", "examples/one", second)
        raise RuntimeError("synthetic rollback")
    assert assets.read_file("examples/one", "original") == b"first"
    with assets.open_file("examples/one", "original") as original:
        with assets.db.transaction() as conn:
            assets.publish_bundle(conn, "example", "examples/one", second)
        with pytest.raises(Exception, match="仍被引用"):
            assets.tombstone(first["original"]["id"], "example")
        assert original.read_bytes() == b"first"
    assert assets.read_file("examples/one", "original") == b"second"
    assets.tombstone(first["original"]["id"], "example")


def test_export_uses_only_assets_and_restored_download_matches(tmp_path):
    """最小安装成品只有资源副本，恢复后原成品和追溯清单可下载"""
    directory = tmp_path / "data"
    app = create_app(Config(data_dir=directory, profile="minimal", token="test"))
    with TestClient(app, headers={"x-resume-token": "test"}) as client:
        resume = client.post(
            "/api/resumes",
            json={
                "name": "合成资料",
                "items": [],
                "document": {
                    "personal": {"name": "统一资源验证"},
                    "sections": [{"id": "projects", "kind": "projects", "title": "项目经历"}],
                },
            },
        ).json()
        response = client.post(f"/api/resumes/{resume['id']}/exports")
        assert response.status_code == 200, response.text
        result = response.json()
        url = f"/api/exports/{result['id']}"
        raw = client.get(url + "/resume.docx").content
        assert not (directory / "exports" / result["id"]).exists()
        assert not list((directory / "workspaces").glob("export-*"))
        with ZipFile(BytesIO(raw)) as archive:
            assert "统一资源验证" in archive.read("word/document.xml").decode()
        backup = tmp_path / "backup.zip"
        backup.write_bytes(client.post("/api/backups").content)
    target = tmp_path / "restored"
    restore_backup(backup, target)
    with TestClient(
        create_app(Config(data_dir=target, token="test")), headers={"x-resume-token": "test"}
    ) as client:
        assert client.get(url + "/resume.docx").content == raw
        assert client.get(url + "/manifest.json").json() == result["manifest"]


def test_project_delete_releases_evidence_in_same_transaction(tmp_path):
    """项目删除解除证据引用，物理原件继续保留到明确回收"""
    from resume_maker.sdk.records import uid

    app = create_app(Config(data_dir=tmp_path / "data", profile="minimal"))
    with TestClient(app):
        services = app.state.services
        project = services.catalog.create_project("合成项目", [])
        identifier = uid()
        services.catalog.publish_evidence(
            project["id"], identifier, "synthetic", {}, {"evidence.txt": b"synthetic"}
        )
        resource = services.assets.file_id(f"snapshots/{identifier}", "evidence.txt")
        services.projects.delete(project["id"])
        assert services.assets.bundle(f"snapshots/{identifier}") is None
        assert services.db.setting(f"asset:{resource}")["references"] == []
        with services.assets.lease(resource) as path:
            assert path.read_bytes() == b"synthetic"
