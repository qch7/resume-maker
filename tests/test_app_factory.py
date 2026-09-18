"""验证接口拆分后的 HTTP 契约、实例隔离、生命周期与静态资源交付"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config, frontend_directory


def without_descriptions(value):
    """去除可改进的文档描述且只比较请求参数、模型和响应格式等通信契约"""
    if isinstance(value, dict):
        return {k: without_descriptions(v) for k, v in value.items() if k != "description"}
    if isinstance(value, list):
        return [without_descriptions(item) for item in value]
    return value


def test_http_contract_matches_current_application(tmp_path):
    """校验当前路径、参数和请求体；服务注入不能泄漏为查询参数"""
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
    expected = json.loads(
        (Path(__file__).parent / "fixtures" / "api-contract.json").read_text(encoding="utf-8")
    )
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
    """应用上下文异常退出后；工作线程仍应收到停止信号并完成回收"""
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
    """缺少构建资源时给出操作提示；环境变量支持独立资源部署"""
    monkeypatch.setenv("RESUME_MAKER_FRONTEND_DIR", str(tmp_path / "custom"))
    assert frontend_directory() == tmp_path / "custom"
    with TestClient(create_app(Config(data_dir=tmp_path / "data"))) as client:
        assert client.get("/").status_code == 503
