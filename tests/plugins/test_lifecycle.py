"""插件切换的用户可见行为及失败原子性"""

import sys
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.runtime.graph import PluginError
from resume_maker.runtime.host import Host, Scope
from resume_maker.runtime.manager import PluginManager
from resume_maker.runtime.state import StateStore
from resume_maker.sdk.context import ServiceKey
from resume_maker.sdk.manifest import Manifest

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


def test_waiting_windows_keep_page_names_and_stable_tab_numbers(tmp_path):
    """页面改名和断连保留可辨认信息，标签序号不因其他窗口关闭而重复"""
    with TestClient(
        create_app(Config(data_dir=tmp_path, token="test", profile="minimal"))
    ) as client:
        for identifier, title, number in (
            ("closed", "ResumeMaker · 模板库", 1),
            ("editor", "ResumeMaker · 项目经历 · 合成项目", 2),
        ):
            response = client.post(
                "/api/plugins/windows",
                headers=HEADERS,
                json={"id": identifier, "generation": 1, "title": title},
            )
            assert response.status_code == 200, response.text
            assert response.json()["number"] == number
        assert (
            client.post(
                "/api/plugins/windows/close",
                headers=HEADERS,
                json={"id": "closed", "generation": 1},
            ).status_code
            == 200
        )
        response = client.post(
            "/api/plugins/windows",
            headers=HEADERS,
            json={"id": "settings", "generation": 1, "title": "ResumeMaker · 个人信息"},
        )
        assert response.json()["number"] == 3
        plan = make_plan(client, {"ext.recruitment"})
        path = prepare(client, plan)
        response = client.post(
            "/api/plugins/windows",
            headers=HEADERS,
            json={
                "id": "editor",
                "generation": 1,
                "title": "ResumeMaker · 项目经历 · 已改名项目",
                "status": "草稿版本冲突，请核对输入。",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["number"] == 2
        assert (
            client.post(
                "/api/plugins/windows",
                headers=HEADERS,
                json={"id": "editor", "generation": 2, "title": "过期标题"},
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/plugins/windows/disconnect",
                headers=HEADERS,
                json={"id": "editor", "generation": 1},
            ).status_code
            == 200
        )
        progress = client.get(path, headers=HEADERS).json()
        detail = progress["windows_detail"]["editor"]
        assert detail["title"] == "ResumeMaker · 项目经历 · 已改名项目"
        assert detail["status"] == "草稿版本冲突，请核对输入。"
        assert detail["number"] == 2 and not detail["connected"]
        assert detail["last_seen"] > 0
        assert set(progress["waiting_windows"]) == {"editor", "settings"}
        assert (
            client.post(
                path + "/apply", headers=HEADERS, json={"digest": plan["digest"]}
            ).status_code
            == 409
        )


@pytest.mark.parametrize("field, length", [("title", 301), ("status", 501)])
def test_window_heartbeat_rejects_unbounded_display_text(tmp_path, field, length):
    """窗口显示信息保持有界，非法请求不会登记窗口"""
    app = create_app(Config(data_dir=tmp_path, token="test", profile="minimal"))
    with TestClient(app) as client:
        response = client.post(
            "/api/plugins/windows",
            headers=HEADERS,
            json={"id": "invalid", "generation": 1, field: "字" * length},
        )
        assert response.status_code == 422
        assert not app.state.runtime.require(ServiceKey("plugins")).windows


def test_expired_preparation_can_cancel_tasks_and_abort_without_unlocking_another_plan(
    tmp_path, monkeypatch
):
    """提交过期仍能取消，取消其他预览不会解除当前准备计划的冻结"""
    from types import SimpleNamespace

    from resume_maker.runtime import manager as manager_module

    app = create_app(Config(data_dir=tmp_path, token="test", profile="minimal"))
    with TestClient(app) as client:
        manager = app.state.runtime.require(ServiceKey("plugins"))
        plan = make_plan(client, {"ext.recruitment"})
        path = prepare(client, plan)
        body = {"digest": plan["digest"]}
        monkeypatch.setattr(
            manager_module, "time", SimpleNamespace(time=lambda: plan["expires_at"] + 1)
        )
        assert client.post(path + "/apply", headers=HEADERS, json=body).status_code == 409
        assert client.post(path + "/cancel-tasks", headers=HEADERS, json=body).status_code == 200
        assert client.post(path + "/abort", headers=HEADERS, json=body).status_code == 200
        assert manager.pending_plan is None and not manager.frozen
        assert not manager.host.frozen_scopes
        assert manager.progress(plan["id"])["state"] == "cancelled"
        active = make_plan(client, {"ext.recruitment"})
        prepare(client, active)
        unrelated = make_plan(client, {"ext.recruitment"})
        cancelled = client.post(
            f"/api/plugins/plans/{unrelated['id']}/abort",
            headers=HEADERS,
            json={"digest": unrelated["digest"]},
        )
        assert cancelled.status_code == 200
        assert manager.pending_plan == active["id"] and manager.frozen
        manager.abort(active["id"], active["digest"])


def test_refreshed_window_joins_preparation_without_discarding_offline_drafts(tmp_path):
    """刷新后的新窗口可管理原计划，旧窗口仍须显式保留恢复副本"""
    app = create_app(Config(data_dir=tmp_path, token="test", profile="minimal"))
    with TestClient(app) as client:
        manager = app.state.runtime.require(ServiceKey("plugins"))
        manager.window("before-refresh", 1)
        plan = make_plan(client, {"ext.recruitment"})
        path = prepare(client, plan)
        manager.disconnect("before-refresh", 1)
        response = client.post(
            "/api/plugins/windows", headers=HEADERS, json={"id": "after-refresh", "generation": 1}
        )
        assert response.status_code == 200, response.text
        assert response.json()["pending_plan"] == plan["id"]
        assert not response.json()["acknowledged"]
        operations = client.get("/api/plugins/operations", headers=HEADERS).json()
        restored = next(item for item in operations if item["id"] == plan["id"])
        assert set(restored["waiting_windows"]) == {"before-refresh", "after-refresh"}
        manager.acknowledge("after-refresh", plan["id"], 1)
        assert (
            client.post(
                path + "/apply", headers=HEADERS, json={"digest": plan["digest"]}
            ).status_code
            == 409
        )
        manager.retain_window("before-refresh", plan["id"], 1)
        assert (
            client.post(
                path + "/apply", headers=HEADERS, json={"digest": plan["digest"]}
            ).status_code
            == 200
        )


def test_failed_activation_rolls_back_routes_and_generation(tmp_path, monkeypatch):
    """注册中途失败不会留下半激活路由或污染已经工作的系统服务"""
    from resume_maker.plugin_packages.ext_recruitment import entry

    app = create_app(Config(data_dir=tmp_path, token="test", profile="minimal"))
    with TestClient(app) as client:
        original = entry.activate

        def broken(context):
            """先注册真实资源再模拟初始化失败"""
            original(context)
            raise RuntimeError("synthetic activation failure")

        monkeypatch.setattr(entry, "activate", broken)
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


@pytest.mark.parametrize("resource", ["barriers", "disposers"])
@pytest.mark.parametrize("persistent", [False, True])
def test_failed_disable_restores_live_services_or_keeps_maintenance(tmp_path, resource, persistent):
    """停用清理失败后真实 API 恢复，持续失败则保留维护和旧配置"""
    app = create_app(Config(data_dir=tmp_path, token="test", profile="minimal"))
    host = app.state.runtime
    manager = host.require(ServiceKey("plugins"))
    waiting, calls = [True], []

    def stop():
        """模拟首次失败或始终无法结束的资源，退出测试前明确解除"""
        calls.append(True)
        if waiting[0] and (persistent or len(calls) == 1):
            raise RuntimeError("synthetic cleanup failure")

    with TestClient(app) as client:
        plan = make_plan(client, {"ext.recruitment"})
        path = prepare(client, plan)
        assert (
            client.post(
                path + "/apply", headers=HEADERS, json={"digest": plan["digest"]}
            ).status_code
            == 200
        )
        original = host.instances["ext.recruitment"]
        getattr(original.scope, resource).append(stop)
        previous = manager.store.read()
        plan = make_plan(client, {"ext.recruitment"})
        path = prepare(client, plan)
        try:
            response = client.post(
                path + "/apply", headers=HEADERS, json={"digest": plan["digest"]}
            )
            assert response.status_code == 409, response.text
            assert manager.store.read() == previous
            assert host.generation == previous["generation"]
            assert "ext.recruitment" in host.selected
            state = client.get("/api/capabilities", headers=HEADERS).json()
            progress = client.get(path, headers=HEADERS).json()
            if persistent:
                assert manager.maintenance and not state["ready"]
                assert "已恢复" not in response.text
                assert original.state == "cleanup-failed"
                assert progress["state"] == "recovery-required"
                assert manager.pending_plan == plan["id"] and manager.frozen
                assert client.get("/api/recruitment", headers=HEADERS).status_code == 409
                assert (
                    client.post(
                        path + "/abort", headers=HEADERS, json={"digest": plan["digest"]}
                    ).status_code
                    == 409
                )
            else:
                assert not manager.maintenance and state["ready"]
                assert "已恢复" in response.text and len(calls) == 2
                assert progress["state"] == "failed"
                assert host.instances["ext.recruitment"] is not original
                assert host.instances["ext.recruitment"].state == "active"
                assert "recruitment" in host.services
                assert client.get("/api/recruitment", headers=HEADERS).status_code == 200
                assert not manager.frozen and manager.pending_plan is None
        finally:
            waiting[0] = False


def test_undeclared_capability_is_not_a_service_locator(tmp_path):
    """业务插件不能借容器语法访问未声明的凭据和执行服务"""
    app = create_app(Config(data_dir=tmp_path, profile="minimal"))
    context = app.state.runtime.instances["sys.resume"]
    with pytest.raises(PluginError, match="未声明"):
        context.require(ServiceKey("credentials"))
    app.state.runtime.close()


@pytest.mark.parametrize("phase", ["old", "candidate"])
def test_rollback_cleanup_failure_keeps_actual_dependency_graph(tmp_path, monkeypatch, phase):
    """旧组合或候选清理失败时都保留实际依赖，不开放业务或重建重叠实例"""
    module = ModuleType("synthetic_rollback")
    waiting = [True]
    released = []

    def activate(context):
        """合成消费者持有提供方资源，停止失败时必须保留提供方"""
        context.provide(ServiceKey(context.instance_id), {"open": True})
        context.effect(lambda: released.append(context.instance_id))
        if context.instance_id == "example.consumer":
            context.require(ServiceKey("example.provider"))

            def stop():
                """模拟仍占用上游资源的执行器"""
                if waiting[0]:
                    raise RuntimeError("synthetic still running")

            context.lifecycle(lambda: None, stop)
            if phase == "candidate":
                raise RuntimeError("synthetic activation failure")

    module.activate = activate
    monkeypatch.setitem(sys.modules, module.__name__, module)
    definitions = {
        key: Manifest(
            id=key,
            title=key,
            version="1.0.0",
            package="synthetic",
            entrypoints={"host": {"mode": "trusted-host", "entry": "synthetic_rollback:activate"}},
            provides={"host": {key: {}}},
            requires={"host": {"example.provider": ">=1.0.0"}} if key.endswith("consumer") else {},
        )
        for key in ("example.provider", "example.consumer")
    }
    host = Host(definitions, set(definitions) if phase == "old" else set(), set())
    host.activate()
    manager = PluginManager(host, StateStore(tmp_path))
    try:
        plan = manager.plan(set() if phase == "old" else set(definitions), 1)
        manager.prepare(plan["id"], plan["digest"])
        with pytest.raises(PluginError, match="维护状态"):
            manager.apply(plan["id"], plan["digest"])
        assert manager.maintenance
        assert manager.plans[plan["id"]]["state"] == "recovery-required"
        assert host.instances["example.consumer"].state == "cleanup-failed"
        assert host.instances["example.provider"].state == "active"
        assert host.require(ServiceKey("example.provider"))["open"]
        assert not released
        with pytest.raises(PluginError, match="尚未就绪"):
            host.check_health()
    finally:
        waiting[0] = False
        host.close()


@pytest.mark.parametrize("operation", ["switch", "close"])
@pytest.mark.parametrize("cycle", [False, True])
def test_contribution_consumers_stop_before_any_provider_resource_is_released(
    tmp_path, monkeypatch, operation, cycle
):
    """集合消费和增强环先完成停止屏障，失败时保留实际被消费的资源"""
    module = ModuleType("synthetic_consumer_drain")
    waiting, events = [True], []
    resources = []

    def activate(context):
        """消费者在注册后持有贡献资源，提供方的关闭动作可被观察"""
        name = context.instance_id
        if name == "a.consumer":
            context.provide(ServiceKey("consumer"), object())
        else:
            resource = {"open": True}
            resources.append(resource)
            context.contribute("example.items", "z.provider/item", resource)
            context.effect(lambda: resource.update(open=False))

        def stop():
            """消费者停止期间仍须能够使用贡献提供方的资源"""
            events.append(("stop", name))
            if name == "a.consumer":
                assert resources[-1]["open"]
                if waiting[0]:
                    raise RuntimeError("synthetic consumer still running")

        context.lifecycle(lambda: None, stop)
        context.effect(lambda: events.append(("release", name)))

    module.activate = activate
    monkeypatch.setitem(sys.modules, module.__name__, module)
    base = dict(
        title="合成排空",
        version="1.0.0",
        package="synthetic",
        entrypoints={
            "host": {"mode": "trusted-host", "entry": "synthetic_consumer_drain:activate"}
        },
    )
    definitions = {
        "a.consumer": Manifest(
            id="a.consumer", **base, provides={"host": {"consumer": {}}}, consumes=["example.items"]
        ),
        "z.provider": Manifest(
            id="z.provider",
            **base,
            contributes={"example.items": ["z.provider/item"]},
            requires={"host": {"consumer": ">=1.0.0"}} if cycle else {},
            enhances=["consumer"] if cycle else [],
        ),
    }
    host = Host(definitions, set(definitions), set())
    host.activate()
    host.start()
    manager = PluginManager(host, StateStore(tmp_path))
    try:
        if operation == "switch":
            plan = manager.plan(set(), 1)
            manager.prepare(plan["id"], plan["digest"])
            with pytest.raises(PluginError, match="维护状态"):
                manager.apply(plan["id"], plan["digest"])
            assert manager.maintenance
        else:
            with pytest.raises(ExceptionGroup):
                host.close()
        assert resources[-1]["open"]
        assert "z.provider" in host.instances
        assert host.collection("example.items")[0].value is resources[-1]
        assert not any(event == "release" for event, _ in events)
    finally:
        waiting[0] = False
        host.close()
    assert not resources[-1]["open"]
    first_release = next(index for index, event in enumerate(events) if event[0] == "release")
    assert all(event[0] == "stop" for event in events[:first_release])
    assert not any(event[0] == "stop" for event in events[first_release:])
    if not cycle:
        assert events.index(("release", "a.consumer")) < events.index(("release", "z.provider"))
