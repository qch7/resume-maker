from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.config import Config


def test_local_api_requires_token_and_rejects_other_origins(tmp_path):
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
