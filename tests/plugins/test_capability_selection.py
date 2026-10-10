"""按产品能力批量选择，保留基础职责、实例绑定和已存资料"""

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.plugins.discovery import selection
from resume_maker.runtime.capability_selection import select_capability_group
from resume_maker.runtime.graph import PluginError
from resume_maker.runtime.instances import expand_instances
from resume_maker.sdk.context import ServiceKey
from resume_maker.sdk.manifest import Manifest
from tests.support.plugins import bundle

HEADERS = {"x-resume-token": "test"}


def manifest(identifier, **fields):
    """构造没有代码入口的领域插件，覆盖供应商和消费约束"""
    return Manifest(id=identifier, title=identifier, version="1.0.0", package="test", **fields)


def test_ocr_shutdown_keeps_manual_honors_and_optional_ai():
    """整组关闭 OCR 后手工荣誉库、AI 会话和基础保护仍可用"""
    manifests, selected, required = selection("standard")
    candidate = set(select_capability_group(manifests, selected, required, "ocr", False))
    assert {"ext.ocr", "provider.rapidocr", "ext.honor-recognition"}.isdisjoint(candidate)
    assert {"ext.honors", "ext.ai-runtime", "ext.ai-conversation", "sys.privacy"} <= candidate
    assert required <= candidate
    assert "ext.ocr" in selected


def test_ai_shutdown_removes_transitive_consumers():
    """跨分组硬依赖逐层停用，模板库和 OCR 仍保留"""
    manifests, selected, required = selection("standard")
    candidate = set(select_capability_group(manifests, selected, required, "ai", False))
    assert {"ext.ai-runtime", "ext.ai-conversation", "ext.template-ai"}.isdisjoint(candidate)
    assert {"ext.template-library", "ext.ocr", "ext.honors"} <= candidate
    candidate = set(select_capability_group(manifests, candidate, required, "ocr", True))
    assert {"ext.honor-recognition", "ext.ai-runtime", "ext.provider-codex"} <= candidate


@pytest.mark.parametrize("group", ["privacy", "storage", "execution"])
def test_required_consumers_prevent_group_shutdown(group):
    """基础职责需要的提供方不能通过领域开关被绕过停用"""
    manifests, selected, required = selection("standard")
    with pytest.raises(PluginError, match="基础插件"):
        select_capability_group(manifests, selected, required, group, False)


def test_group_enable_preserves_selected_provider_and_requires_ambiguous_choice():
    """已有供应商不被替换，未选供应商时拒绝猜测唯一提供方"""
    group = [{"id": "speech", "title": "语音"}]
    manifests = {
        key: manifest(key, capability_groups=group, provides={"host": {"speech": {}}})
        for key in ("example.first", "example.second")
    }
    assert select_capability_group(manifests, {"example.second"}, set(), "speech", True) == [
        "example.second"
    ]
    with pytest.raises(PluginError, match="冲突"):
        select_capability_group(manifests, set(), set(), "speech", True)
    manifests["example.reader"] = manifest(
        "example.reader",
        capability_groups=[{"id": "reader", "title": "朗读"}],
        requires={"remote": {"speech": ">=1.0.0 <2.0.0"}},
    )
    with pytest.raises(PluginError, match="选择一个提供方"):
        select_capability_group(manifests, set(), set(), "reader", True)


def test_shutdown_uses_explicit_bindings_and_keeps_unbound_collection():
    """移除绑定提供方时只停用绑定消费者，其他集合消费者继续可用"""
    definitions = {
        key: manifest(
            key,
            capability_groups=[{"id": key, "title": key}],
            instances={"multiple": True},
            provides={"host": {"speech": {"cardinality": "many"}}},
        )
        for key in ("example.first", "example.second")
    }
    for key in ("example.bound", "example.unbound", "example.leaf"):
        definitions[key] = manifest(
            key,
            requires={"remote": {"speech": {"cardinality": "many"}}}
            if key != "example.leaf"
            else {},
            plugins={"example.bound": ">=1.0.0"} if key == "example.leaf" else {},
        )
    manifests, _ = expand_instances(
        definitions,
        [
            {"id": "example.extra", "plugin": "example.first"},
            {
                "id": "example.bound",
                "plugin": "example.bound",
                "bindings": {"remote": {"speech": "example.extra"}},
            },
        ],
    )
    candidate = select_capability_group(manifests, set(manifests), set(), "example.first", False)
    assert candidate == ["example.second", "example.unbound"]


def test_task_members_are_not_enabled_by_workspace_group():
    """同组任务实例仍随任务启动，工作区开关只选择长期实例"""
    group = [{"id": "speech", "title": "语音"}]
    manifests = {
        "example.task": manifest(
            "example.task", capability_groups=group, instances={"scope": "task"}
        ),
        "example.workspace": manifest("example.workspace", capability_groups=group),
    }
    assert select_capability_group(manifests, set(), set(), "speech", True) == ["example.workspace"]
    with pytest.raises(PluginError, match="分类不存在"):
        select_capability_group(manifests, set(), set(), "unknown", True)


def test_legacy_external_ocr_provider_joins_group_and_shuts_down(tmp_path):
    """已安装的旧 OCR 引擎自动归组，停用不波及只消费公共日志的其他领域"""
    app = create_app(Config(data_dir=tmp_path / "data", token="test", profile="minimal"))
    host = app.state.runtime
    manager = host.require(ServiceKey("plugins"))
    archive = tmp_path / "legacy.rmp"
    bundle(archive, extra={"provides": {"host": {"ocr.backend": {}}}, "contributes": {}})
    inspection = host.bootstrap["package_store"].inspect(archive)
    manager.install(archive, inspection["digest"], inspection["trust_modes"])
    with TestClient(app) as client:
        plugins = {
            item["id"]: item
            for item in client.get("/api/plugins", headers=HEADERS).json()["plugins"]
        }
        assert plugins["community.example"]["capability_groups"] == [
            {"id": "ocr", "title": "OCR 识别"}
        ]
        selected = host.selected | {"community.example", "ext.ocr"}
        response = client.post(
            "/api/plugins/capability-selection",
            headers=HEADERS,
            json={
                "group": "ocr",
                "enabled": False,
                "selected": sorted(selected),
                "generation": host.generation,
            },
        )
        assert response.status_code == 200, response.text
        assert set(response.json()["selected"]) == host.selected


def test_log_group_http_preview_apply_and_restore_preserves_data(tmp_path):
    """日志领域开关经过现有计划生效，系统日志及项目资料跨重启保留"""
    directory = tmp_path / "data"
    app = create_app(Config(data_dir=directory, token="test", profile="minimal"))
    host = app.state.runtime
    manager = host.require(ServiceKey("plugins"))
    with TestClient(app) as client:
        response = client.get("/api/plugins", headers=HEADERS)
        plugins = {item["id"]: item for item in response.json()["plugins"]}
        assert plugins["sys.activity"]["capability_groups"] == [{"id": "logs", "title": "日志"}]
        project = client.post("/api/projects", headers=HEADERS, json={"name": "分组验收"}).json()
        for enabled in (True, False):
            body = {
                "group": "logs",
                "enabled": enabled,
                "selected": sorted(host.selected),
                "generation": host.generation,
            }
            assert client.post("/api/plugins/capability-selection", json=body).status_code == 401
            stale = client.post(
                "/api/plugins/capability-selection",
                headers=HEADERS,
                json={**body, "generation": host.generation + 1},
            )
            assert stale.status_code == 409
            response = client.post("/api/plugins/capability-selection", headers=HEADERS, json=body)
            assert response.status_code == 200, response.text
            candidate = response.json()["selected"]
            assert ("ext.activity-ui" in candidate) is enabled
            assert ("ext.activity-ui" in host.selected) is not enabled
            response = client.post(
                "/api/plugins/plans",
                headers=HEADERS,
                json={"selected": candidate, "generation": host.generation},
            )
            assert response.status_code == 200, response.text
            plan = response.json()
            manager.prepare(plan["id"], plan["digest"])
            manager.apply(plan["id"], plan["digest"])
            assert ("ext.activity-ui" in host.selected) is enabled
            assert "sys.activity" in host.selected
            assert client.get(f"/api/projects/{project['id']}", headers=HEADERS).status_code == 200
    with TestClient(create_app(Config(data_dir=directory, token="test"))) as client:
        assert client.get(f"/api/projects/{project['id']}", headers=HEADERS).status_code == 200
        plugins = {
            item["id"]: item
            for item in client.get("/api/plugins", headers=HEADERS).json()["plugins"]
        }
        assert not plugins["ext.activity-ui"]["enabled"]
        assert plugins["sys.activity"]["enabled"]
