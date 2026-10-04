"""插件切换的用户可见行为及失败原子性"""

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.runtime.graph import PluginError
from resume_maker.runtime.host import Scope
from resume_maker.sdk.context import ServiceKey

HEADERS = {"x-resume-token": "test"}


def make_plan(client, enabled):
    """按客户端当前看到的代次生成组合计划"""
    current = client.get("/api/capabilities", headers=HEADERS).json()
    selected = set(current["plugins"])
    selected.symmetric_difference_update(enabled)
    response = client.post(
        "/api/plugins/plans",
        headers=HEADERS,
        json={"selected": sorted(selected), "generation": current["generation"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def prepare(client, plan):
    """进入草稿刷新阶段并返回可以复用的请求路径"""
    path = f"/api/plugins/plans/{plan['id']}"
    response = client.post(path + "/prepare", headers=HEADERS, json={"digest": plan["digest"]})
    assert response.status_code == 200, response.text
    return path


def test_enable_disable_preserves_data_and_survives_restart(tmp_path):
    """选装插件无需重启即可获得完整 API，停用保留资料并拒绝旧代次写入"""
    config = Config(data_dir=tmp_path, token="test", profile="minimal")
    with TestClient(create_app(config)) as client:
        plan = make_plan(client, {"ext.recruitment"})
        path = prepare(client, plan)
        response = client.post(path + "/apply", headers=HEADERS, json={"digest": plan["digest"]})
        assert response.status_code == 200, response.text
        assert response.json()["generation"] == 2
        assert client.get("/api/recruitment", headers=HEADERS).status_code == 200
        stale = client.post(
            "/api/projects",
            headers={**HEADERS, "x-resume-generation": "1"},
            json={"name": "过期窗口"},
        )
        assert stale.status_code == 409, stale.text
        assert (
            client.post(
                path + "/apply", headers=HEADERS, json={"digest": plan["digest"]}
            ).status_code
            == 409
        )
    with TestClient(create_app(Config(data_dir=tmp_path, token="test"))) as client:
        assert client.get("/api/recruitment", headers=HEADERS).status_code == 200
        plan = make_plan(client, {"ext.recruitment"})
        path = prepare(client, plan)
        response = client.post(path + "/apply", headers=HEADERS, json={"digest": plan["digest"]})
        assert response.status_code == 200, response.text
        assert client.get("/api/recruitment", headers=HEADERS).status_code == 404


def test_profile_roundtrip_keeps_management_channel_and_route_publication(tmp_path):
    """管理器参与重建仍能确认窗口及发布新路由，连续组合切换不丢协调状态"""
    from resume_maker.plugins.discovery import selection

    app = create_app(Config(data_dir=tmp_path, token="test", profile="standard"))
    original = app.state.runtime.require(ServiceKey("plugins"))
    with TestClient(app) as client:
        for expected, profile in enumerate(("minimal", "standard", "minimal"), start=1):
            registered = client.post(
                "/api/plugins/windows",
                headers=HEADERS,
                json={"id": "active-window", "generation": expected},
            )
            assert registered.status_code == 200, registered.text
            response = client.post(
                "/api/plugins/plans",
                headers=HEADERS,
                json={"selected": sorted(selection(profile)[1]), "generation": expected},
            )
            assert response.status_code == 200, response.text
            plan = response.json()
            assert "sys.plugins" in plan["affected"]
            path = prepare(client, plan)
            registered = client.post(
                "/api/plugins/windows",
                headers=HEADERS,
                json={"id": "active-window", "generation": expected},
            )
            assert registered.status_code == 200, registered.text
            assert registered.json()["pending_plan"] == plan["id"]
            ack = client.post(
                path + "/acknowledge",
                headers=HEADERS,
                json={"id": "active-window", "generation": expected},
            )
            assert ack.status_code == 200, ack.text
            applied = client.post(path + "/apply", headers=HEADERS, json={"digest": plan["digest"]})
            assert applied.status_code == 200, applied.text
            assert applied.json()["generation"] == expected + 1
            assert app.state.runtime.require(ServiceKey("plugins")) is original
            assert client.get("/api/recruitment", headers=HEADERS).status_code == (
                200 if profile == "standard" else 404
            )
            assert client.get("/api/plugins", headers=HEADERS).status_code == 200


def test_all_windows_must_acknowledge_and_flush_channel_remains_open(tmp_path):
    """任一窗口未确认都阻止切换，草稿通道不因业务冻结提前关闭"""
    app = create_app(Config(data_dir=tmp_path, token="test", profile="minimal"))
    with TestClient(app) as client:
        for window in ("one", "two"):
            assert (
                client.post(
                    "/api/plugins/windows", headers=HEADERS, json={"id": window, "generation": 1}
                ).status_code
                == 200
            )
        plan = make_plan(client, {"ext.recruitment"})
        path = prepare(client, plan)
        body = {"digest": plan["digest"]}
        assert client.post(path + "/apply", headers=HEADERS, json=body).status_code == 409
        manager = app.state.runtime.require(ServiceKey("plugins"))
        with manager.request("ext.recruitment", write=True, flush=True, generation=1):
            pass
        with pytest.raises(Exception, match="切换"):
            with manager.request("ext.recruitment", write=True, generation=1):
                pass
        for window in ("one", "two"):
            response = client.post(
                path + "/acknowledge", headers=HEADERS, json={"id": window, "generation": 1}
            )
            assert response.status_code == 200
        assert client.post(path + "/apply", headers=HEADERS, json=body).status_code == 200


def test_failed_activation_rolls_back_routes_and_generation(tmp_path, monkeypatch):
    """注册中途失败不会留下半激活路由或污染已经工作的系统服务"""
    from resume_maker.plugins import features

    app = create_app(Config(data_dir=tmp_path, token="test", profile="minimal"))
    with TestClient(app) as client:
        original = features.recruitment

        def broken(context):
            """先注册真实资源再模拟初始化失败"""
            original(context)
            raise RuntimeError("synthetic activation failure")

        monkeypatch.setattr(features, "recruitment", broken)
        plan = make_plan(client, {"ext.recruitment"})
        path = prepare(client, plan)
        response = client.post(path + "/apply", headers=HEADERS, json={"digest": plan["digest"]})
        assert response.status_code == 409, response.text
        assert client.get("/api/recruitment", headers=HEADERS).status_code == 404
        assert client.get("/api/capabilities", headers=HEADERS).json()["generation"] == 1
        assert (
            client.post("/api/projects", headers=HEADERS, json={"name": "恢复后"}).status_code
            == 200
        )
        assert "recruitment" not in app.state.runtime.services


def test_scope_cleanup_retries_only_failed_resources():
    """清理故障不会假报完成，重复关闭只重试未成功的资源"""
    seen = []
    scope = Scope()

    def unstable():
        """首次回收失败，第二次释放同一资源"""
        seen.append("unstable")
        if seen.count("unstable") == 1:
            raise RuntimeError("busy")

    scope.disposers.extend([lambda: seen.append("first"), unstable, lambda: seen.append("last")])
    with pytest.raises(ExceptionGroup):
        scope.close()
    assert not scope.closed
    scope.close()
    scope.close()
    assert seen == ["last", "unstable", "first", "unstable"]


def test_undeclared_capability_is_not_a_service_locator(tmp_path):
    """业务插件不能借容器语法访问未声明的凭据和执行服务"""
    app = create_app(Config(data_dir=tmp_path, profile="minimal"))
    context = app.state.runtime.instances["sys.resume"]
    with pytest.raises(PluginError, match="未声明"):
        context.require(ServiceKey("credentials"))
    app.state.runtime.close()
