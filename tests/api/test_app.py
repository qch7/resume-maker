"""HTTP 契约、访问校验、应用生命周期和业务往返"""

import json

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config, frontend_directory


def test_sidebar_activity_tracks_drafts_and_conversation_edits(tmp_path, monkeypatch):
    """验证项目活动时间聚合草稿和会话修改，重复值不会刷新时间"""
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
            """聚合项目活动时间、会话、简历、模板及最近任务，供工作台轮询"""
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
    """验证本机接口要求实例令牌并拒绝外部 Origin 和 Host"""
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
    """验证应用重启后项目、会话标题及未发送草稿仍可恢复"""
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
    """当前请求提交全部字段，过期提交被拒绝，恢复后项目默认版本来自主分支"""
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


def without_descriptions(value):
    """去除可改进的文档描述且只比较请求参数、模型和响应格式等通信契约"""
    if isinstance(value, dict):
        return {k: without_descriptions(v) for k, v in value.items() if k != "description"}
    if isinstance(value, list):
        return [without_descriptions(item) for item in value]
    return value


def test_http_contract_matches_current_application(tmp_path, fixtures_dir):
    """校验当前路径、参数和请求体，服务注入不能泄漏为查询参数"""
    spec = create_app(Config(data_dir=tmp_path)).openapi()
    actual = {
        "paths": {
            path: {
                method: {
                    key: value
                    for key, value in operation.items()
                    if key in {"parameters", "requestBody", "responses"}
                }
                for method, operation in methods.items()
            }
            for path, methods in spec["paths"].items()
        },
        "schemas": spec["components"]["schemas"],
    }
    expected = json.loads((fixtures_dir / "api-contract.json").read_text(encoding="utf-8"))
    assert without_descriptions(actual) == without_descriptions(expected)


def test_applications_keep_data_and_tokens_isolated(tmp_path):
    """同时存在的两个应用不得共享数据库、服务对象或访问令牌"""
    left = create_app(Config(data_dir=tmp_path / "left", token="left"))
    right = create_app(Config(data_dir=tmp_path / "right", token="right"))
    source = tmp_path / "source"
    source.mkdir()
    assert left.state.services.jobs is not right.state.services.jobs
    with TestClient(left) as a, TestClient(right) as b:
        result = a.post(
            "/api/projects",
            json={"name": "隔离项目", "roots": [str(source)]},
            headers={"x-resume-token": "left"},
        )
        assert result.status_code == 200
        assert b.get("/api/state", headers={"x-resume-token": "left"}).status_code == 401
        assert b.get("/api/state", headers={"x-resume-token": "right"}).json()["projects"] == []


def test_lifespan_stops_worker_even_on_exception(tmp_path):
    """应用上下文异常退出后，工作线程仍应收到停止信号并完成回收"""
    app = create_app(Config(data_dir=tmp_path))
    queue = app.state.services.jobs
    with pytest.raises(RuntimeError, match="模拟关闭异常"), TestClient(app):
        assert queue.worker.is_alive()
        raise RuntimeError("模拟关闭异常")
    assert queue.stopped.is_set()
    assert not queue.worker.is_alive()


def test_static_assets_and_current_token_are_served(tmp_path):
    """页面和资源从配置位置读取且只有首页的占位符替换为当前实例令牌"""
    frontend = tmp_path / "web"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text('<meta content="__RESUME_TOKEN__">', encoding="utf-8")
    (frontend / "assets" / "app.js").write_text("/* 构建资源 */", encoding="utf-8")
    app = create_app(Config(data_dir=tmp_path / "data", frontend=frontend, token="test-token"))
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert 'content="test-token"' in response.text
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/assets/app.js").status_code == 200
        assert (
            client.get(
                "/api/projects/missing", headers={"x-resume-token": "test-token"}
            ).status_code
            == 404
        )


def test_missing_frontend_and_explicit_directory(tmp_path, monkeypatch):
    """缺少构建资源时给出操作提示，环境变量支持独立资源部署"""
    monkeypatch.setenv("RESUME_MAKER_FRONTEND_DIR", str(tmp_path / "custom"))
    assert frontend_directory() == tmp_path / "custom"
    with TestClient(create_app(Config(data_dir=tmp_path / "data"))) as client:
        assert client.get("/").status_code == 503
