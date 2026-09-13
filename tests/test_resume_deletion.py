"""验证方案删除、过期写入保护、历史文件保留以及旧数据库升级。"""

import sqlite3

from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.infrastructure.database import SCHEMA, Database, dump, now
from resume_maker.services.catalog import Catalog
from resume_maker.services.workspace import Workspace


def test_delete_resume_preserves_projects_exports_and_other_plans(tmp_path):
    """删除只移除目标方案，拒绝未鉴权或过期版本请求，并保留已导出文件。"""
    config = Config(data_dir=tmp_path / "data", token="test-token")
    app = create_app(config)
    source = tmp_path / "source"
    source.mkdir()
    headers = {"x-resume-token": config.token}
    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            headers=headers,
            json={
                "name": "项目",
                "roots": [str(source)],
            },
        ).json()
        item = {
            "project_id": project["id"],
            "revision_id": project["head_revision"],
            "highlight_ids": [],
        }
        target = client.post(
            "/api/resumes", headers=headers, json={"name": "待删除方案", "items": [item]}
        ).json()
        other = client.post(
            "/api/resumes", headers=headers, json={"name": "保留方案", "items": [item]}
        ).json()
        export_id = "retained-export"
        directory = config.data_dir / "exports" / export_id
        directory.mkdir()
        document = directory / "resume.docx"
        document.write_bytes(b"retained document")
        with app.state.services.db.transaction() as conn:
            conn.execute(
                "INSERT INTO exports VALUES (?,?,?,?,?,?)",
                (
                    export_id,
                    target["id"],
                    dump({"resume": target}),
                    None,
                    None,
                    now(),
                ),
            )
        url = f"/api/resumes/{target['id']}"
        assert client.delete(url, params={"version": target["version"]}).status_code == 401
        assert client.delete(url, params={"version": 0}, headers=headers).status_code == 422
        assert (
            client.delete(
                url, params={"version": target["version"] + 1}, headers=headers
            ).status_code
            == 409
        )
        assert len(client.get("/api/state", headers=headers).json()["resumes"]) == 2
        assert (
            client.delete(url, params={"version": target["version"]}, headers=headers).status_code
            == 200
        )
        state = client.get("/api/state", headers=headers).json()
        assert [resume["id"] for resume in state["resumes"]] == [other["id"]]
        assert state["projects"][0]["id"] == project["id"]
        assert (
            client.get(f"/api/revisions/{project['head_revision']}", headers=headers).status_code
            == 200
        )
        assert (
            client.get(f"/api/exports/{export_id}/resume.docx", headers=headers).content
            == b"retained document"
        )
        assert client.post(url + "/exports", headers=headers).status_code == 404
        assert (
            client.put(
                url,
                headers=headers,
                json={
                    "name": "过期窗口",
                    "items": [item],
                    "version": target["version"],
                },
            ).status_code
            == 404
        )
        assert (
            client.delete(url, params={"version": target["version"]}, headers=headers).status_code
            == 404
        )
        assert document.read_bytes() == b"retained document"
    with TestClient(create_app(config)) as restarted:
        assert [
            r["id"] for r in restarted.get("/api/state", headers=headers).json()["resumes"]
        ] == [other["id"]]
        assert (
            restarted.delete(
                f"/api/resumes/{other['id']}", params={"version": other["version"]}, headers=headers
            ).status_code
            == 200
        )
        assert restarted.get("/api/state", headers=headers).json()["resumes"] == []


def test_old_database_migrates_without_losing_saved_resumes(tmp_path):
    """首版数据库自动升级且保留原方案，重复打开不会重复执行迁移。"""
    path = tmp_path / "resume.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA + "PRAGMA user_version=1;")
        conn.execute(
            "INSERT INTO resumes VALUES (?,?,?,?,?,?,?)",
            ("existing", "旧方案", None, "[]", 1, now(), now()),
        )
    db = Database(path)
    assert db.one("PRAGMA user_version")["user_version"] == 4
    catalog = Catalog(db)
    assert Workspace(catalog).state()["resumes"][0]["name"] == "旧方案"
    catalog.delete_resume("existing", 1)
    assert Workspace(Catalog(Database(path))).state()["resumes"] == []
    assert db.one("SELECT * FROM resumes WHERE id='existing'")["name"] == "旧方案"
