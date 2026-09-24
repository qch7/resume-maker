"""草稿在服务重启和备份恢复后仍可继续，冲突及删除不能覆盖新输入"""

import json

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import Database
from resume_maker.infrastructure.storage import create_backup, restore_backup
from resume_maker.services.workspace_storage import WorkspaceStorage


def test_drafts_survive_restart_backup_without_publishing(catalog, tmp_path):
    """照片、简历、模板和荣誉输入独立备份，不提前生成任何正式资料"""
    directory = catalog.db.path.parent
    service = WorkspaceStorage(catalog.db)
    values = {
        "rm.resume.v2.new": {"document": {"personal": {"photo": "data:image/png;base64,cGhvdG8="}}},
        "rm.template.editor.test": {"name": "未保存映射", "plan": {"fields": []}},
        "rm.honor.draft.new": {"fields": {"name": "人工核对中"}},
        "rm.settings.privacy": {"terms": "测试学校", "version": 0},
    }
    for key, value in values.items():
        service.save(key, json.dumps(value), 0)
    reopened = WorkspaceStorage(Database(directory / "resume.db"))
    assert reopened.state() == service.state()
    assert not catalog.db.all("SELECT * FROM resumes")
    assert not catalog.db.all("SELECT * FROM templates")
    archive = create_backup(catalog.db, directory)
    (directory / "template-cache").mkdir()
    previous = restore_backup(archive, directory)
    restored = WorkspaceStorage(Database(directory / "resume.db"))
    assert previous.is_dir()
    assert restored.state()["values"] == service.state()["values"]
    assert restored.namespace != service.namespace


def test_conflicts_deletions_and_lost_acknowledgement(catalog):
    """重试同值写入幂等，删除标记阻止旧窗口复活草稿"""
    storage = WorkspaceStorage(catalog.db)
    first = storage.save("rm.resume.v2.new", "first", 0)
    assert storage.save("rm.resume.v2.new", "first", 0) == first
    with pytest.raises(Problem, match="其他窗口"):
        storage.save("rm.resume.v2.new", "stale", 0)
    deleted = storage.save("rm.resume.v2.new", None, first["version"])
    assert deleted["version"] == 2
    with pytest.raises(Problem, match="其他窗口"):
        storage.save("rm.resume.v2.new", "stale", first["version"])
    assert storage.state()["values"]["rm.resume.v2.new"]["value"] is None


def test_storage_http_auth_bounds_and_isolation(tmp_path):
    """草稿接口保留本机鉴权，拒绝越界键和过大内容，实例不共享恢复空间"""
    app = create_app(Config(data_dir=tmp_path / "left", token="test"))
    with TestClient(app) as client:
        assert client.get("/api/workspace-storage").status_code == 401
        headers = {"x-resume-token": "test"}
        response = client.put(
            "/api/workspace-storage/rm.layout",
            headers=headers,
            json={"value": "test", "version": 0},
        )
        assert response.status_code == 200
        assert (
            client.put(
                "/api/workspace-storage/provider",
                headers=headers,
                json={"value": "bad", "version": 0},
            ).status_code
            == 400
        )
        left = client.get("/api/workspace-storage", headers=headers).json()
    right = WorkspaceStorage(Database(tmp_path / "right" / "resume.db"))
    assert left["namespace"] != right.namespace
    assert not right.state()["values"]
    with pytest.raises(Problem, match="8 MB"):
        right.save("rm.large", "字" * 2_666_667, 0)
