"""test_api.py：模块职责与调用关系见 docs/architecture.md。"""

from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config


def test_sidebar_activity_tracks_drafts_and_conversation_edits(tmp_path, monkeypatch):
    """验证项目活动时间聚合草稿与会话修改，重复值不会刷新时间。"""
    stamp = "2026-01-01T00:00:00Z"
    monkeypatch.setattr("resume_maker.services.catalog.now", lambda: stamp)
    monkeypatch.setattr("resume_maker.services.conversations.now", lambda: stamp)
    source = tmp_path / "source"
    source.mkdir()
    headers = {"x-resume-token": "test-token"}
    with TestClient(create_app(Config(data_dir=tmp_path / "data", token="test-token"))) as client:
        project = client.post(
            "/api/projects", json={"name": "项目", "roots": [str(source)]}, headers=headers
        ).json()

        def state():
            """聚合项目活动时间、会话、简历、模板及最近任务，供工作台轮询。"""
            return client.get("/api/state", headers=headers).json()

        conversation = state()["conversations"][0]
        stamp = "2026-01-02T00:00:00Z"
        response = client.put(
            f"/api/projects/{project['id']}/draft",
            headers=headers,
            json={
                "base_revision": project["head_revision"],
                "field": "highlight:test",
                "value": {"title": "亮点", "text": "草稿内容", "evidence": []},
                "version": 0,
            },
        )
        assert response.status_code == 200, response.text
        assert state()["projects"][0]["activity_at"] == stamp
        assert state()["projects"][0]["updated_at"] == project["updated_at"]

        path = f"/api/conversations/{conversation['id']}"
        for field, value, day in [("title", "修改名称", "03"), ("input_draft", "输入草稿", "04")]:
            stamp = f"2026-01-{day}T00:00:00Z"
            response = client.patch(path, headers=headers, json={field: value})
            assert response.status_code == 200, response.text
            assert response.json()["updated_at"] == stamp
            assert state()["projects"][0]["activity_at"] == stamp

        previous = stamp
        stamp = "2026-01-05T00:00:00Z"
        client.get(path, headers=headers)
        client.patch(path, headers=headers, json={"title": "修改名称", "input_draft": "输入草稿"})
        assert state()["projects"][0]["activity_at"] == previous


def test_local_api_requires_token_and_rejects_other_origins(tmp_path):
    """验证本机接口要求实例令牌并拒绝外部 Origin 和 Host。"""
    app = create_app(Config(data_dir=tmp_path, token="test-token"))
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/state").status_code == 401
        assert client.get("/api/state", headers={"x-resume-token": "test-token"}).status_code == 200
        assert (
            client.get(
                "/api/state",
                headers={"x-resume-token": "test-token", "origin": "https://external.example"},
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/state", headers={"x-resume-token": "test-token", "host": "external.example"}
            ).status_code
            == 400
        )


def test_project_and_conversation_persist_after_app_restart(tmp_path):
    """验证应用重启后项目、会话标题及未发送草稿仍可恢复。"""
    source = tmp_path / "source"
    source.mkdir()
    config = Config(data_dir=tmp_path / "data", token="test-token")
    headers = {"x-resume-token": "test-token"}
    with TestClient(create_app(config)) as client:
        result = client.post(
            "/api/projects", json={"name": "项目", "roots": [str(source)]}, headers=headers
        )
        assert result.status_code == 200, result.text
        project_id = result.json()["id"]
        conversation = client.post(
            f"/api/projects/{project_id}/conversations", headers=headers
        ).json()
        saved = client.patch(
            f"/api/conversations/{conversation['id']}",
            headers=headers,
            json={"input_draft": "未发送草稿", "title": "后端岗位版"},
        )
        assert saved.status_code == 200
    with TestClient(create_app(config)) as client:
        state = client.get("/api/state", headers=headers).json()
        assert state["projects"][0]["id"] == project_id
        restored = next(c for c in state["conversations"] if c["id"] == conversation["id"])
        assert restored["input_draft"] == "未发送草稿"
        assert restored["title"] == "后端岗位版"


def test_commit_and_restore_publish_complete_working_copy(tmp_path):
    """当前请求提交全部字段，过期提交被拒绝，恢复后项目默认版本来自主分支。"""
    source = tmp_path / "source"
    source.mkdir()
    config = Config(data_dir=tmp_path / "data", token="test")
    with TestClient(create_app(config), headers={"x-resume-token": "test"}) as client:
        project = client.post("/api/projects", json={"name": "项目", "roots": [str(source)]}).json()
        base = project["head_revision"]
        url = f"/api/projects/{project['id']}"
        for field, value in [
            ("meta", {"title": "新标题"}),
            ("highlight:one", {"title": "亮点", "text": "实现正文", "evidence": []}),
        ]:
            assert (
                client.put(
                    url + "/draft", json={"base_revision": base, "field": field, "value": value}
                ).status_code
                == 200
            )
        body = {"base_revision": base, "expected_head": base}
        response = client.post(url + "/revisions", json=body)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["content"]["title"] == "新标题"
        assert saved["content"]["highlights"][0]["text"] == "实现正文"
        assert client.get(url).json()["working"]["drafts"] == []
        assert client.post(url + "/revisions", json=body).status_code == 409
        response = client.post(
            url + "/restore", json={"base_revision": base, "expected_head": saved["id"]}
        )
        assert response.status_code == 200, response.text
        restored = response.json()
        assert restored["parent_id"] == saved["id"]
        assert restored["content"]["title"] == "项目"
        assert restored["content"]["highlights"] == []
        assert client.get("/api/state").json()["projects"][0]["head_revision"] == restored["id"]
