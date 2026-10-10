"""外部能力提供方在同一计划替换，消费者及旧配置保持一致"""

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.sdk.context import ServiceKey
from tests.support.plugins import bundle


@pytest.mark.parametrize(
    ("capability", "title"),
    [("speech.backend", "语音合成引擎"), ("translation.backend", "翻译引擎")],
)
def test_new_domain_provider_metadata_and_replacement(tmp_path, capability, title):
    """新增领域的名称通过管理接口发布，替换计划应用后才切换服务"""
    app = create_app(Config(data_dir=tmp_path / "data", token="test", profile="minimal"))
    host = app.state.runtime
    manager = host.require(ServiceKey("plugins"))
    for identifier, label, metadata in [
        ("community.original", "original", {}),
        ("community.example", "candidate", {"title": title}),
    ]:
        archive = tmp_path / f"{identifier}.rmp"
        code = f'''from resume_maker.sdk.context import ServiceKey

def activate(context):
    """注册合成领域服务，不读取真实材料或访问供应商"""
    context.provide(ServiceKey("{capability}"), "{label}")
'''
        bundle(
            archive,
            extra={
                "id": identifier,
                "provides": {"host": {capability: metadata}},
                "contributes": {},
            },
            artifacts_extra={"python/plugin.py": code.encode()},
        )
        inspected = host.bootstrap["package_store"].inspect(archive)
        manager.install(archive, inspected["digest"], inspected["trust_modes"])
    with TestClient(app) as client:
        original = manager.plan(host.selected | {"community.original"}, host.generation)
        manager.prepare(original["id"], original["digest"])
        manager.apply(original["id"], original["digest"])
        response = client.get("/api/plugins", headers={"x-resume-token": "test"})
        assert response.status_code == 200, response.text
        plugins = {item["id"]: item for item in response.json()["plugins"]}
        assert plugins["community.example"]["provided"]["host"][capability]["title"] == title
        assert plugins["community.original"]["provided"]["host"][capability]["title"] is None
        candidate = (host.selected - {"community.original"}) | {"community.example"}
        response = client.post(
            "/api/plugins/plans",
            headers={"x-resume-token": "test"},
            json={"selected": sorted(candidate), "generation": host.generation},
        )
        assert response.status_code == 200, response.text
        plan = response.json()
        assert "community.original" in plan["removed"]
        assert "community.example" in plan["added"]
        assert host.require(ServiceKey(capability)) == "original"
        manager.prepare(plan["id"], plan["digest"])
        manager.apply(plan["id"], plan["digest"])
        assert host.require(ServiceKey(capability)) == "candidate"


def test_package_replacement_plan_preserves_explicit_bindings_and_config_edits(tmp_path):
    """首次安装就在同一计划切换提供方，普通配置草稿不会丢失"""
    app = create_app(Config(data_dir=tmp_path / "data", token="test", profile="minimal"))
    host = app.state.runtime
    manager = host.require(ServiceKey("plugins"))
    archive = tmp_path / "candidate.rmp"
    bundle(
        archive,
        extra={
            "provides": {"host": {"ocr.backend": {"cardinality": "one"}}},
            "config": {"label": "original"},
            "config_schema": {"type": "object", "properties": {"label": {"type": "string"}}},
        },
    )
    with TestClient(app) as client:
        original = manager.plan(host.selected | {"ext.ocr", "provider.rapidocr"}, host.generation)
        manager.prepare(original["id"], original["digest"])
        manager.apply(original["id"], original["digest"])
        inspection = host.bootstrap["package_store"].inspect(archive)
        response = client.post(
            "/api/plugins/packages/plans",
            headers={"x-resume-token": "test"},
            json={
                "packages": [
                    {
                        "path": str(archive),
                        "digest": inspection["digest"],
                        "trusted_modes": inspection["trust_modes"],
                    }
                ],
                "generation": host.generation,
                "selected": sorted((host.selected - {"provider.rapidocr"}) | {"community.example"}),
                "instances": [
                    {
                        "id": "ext.ocr",
                        "plugin": "ext.ocr",
                        "bindings": {"host": {"ocr.backend": "community.example"}},
                    }
                ],
                "config_edits": [
                    {
                        "instance": "community.example",
                        "operation": "set",
                        "path": ["label"],
                        "value": "candidate",
                    }
                ],
            },
        )
        assert response.status_code == 200, response.text
        plan = response.json()
        assert "provider.rapidocr" in plan["removed"] and "ext.ocr" in plan["affected"]
        assert plan["configuration"]["configs"]["community.example"]["label"] == "candidate"
        assert "provider.rapidocr" in host.selected
        assert "community.example" not in host.selected


def test_replacement_plan_preserves_consumer_and_publishes_only_after_apply(tmp_path):
    """同时移除旧引擎并加入新引擎，计划预览保持活动提供方不变"""
    directory = tmp_path / "data"
    app = create_app(Config(data_dir=directory, token="test", profile="minimal"))
    host = app.state.runtime
    manager = host.require(ServiceKey("plugins"))
    archive = tmp_path / "ocr.rmp"
    code = '''from resume_maker.sdk.context import ServiceKey
class Backend:
    def read_document(self, path, cancelled):
        """返回合成 OCR 文字，不读取真实文件或访问供应商"""
        return {"pages": [{"width": 100, "height": 100, "method": "synthetic",
            "blocks": [{"text": "synthetic", "box": [0.1, 0.1, 0.9, 0.2], "confidence": 1.0}]}],
            "text": "synthetic", "seconds": 0.0, "needs_review": False, "notice": "synthetic"}
    def close(self):
        """合成提供方没有后台资源"""
        pass
def activate(context):
    """通过公开服务键注册可替换提供方"""
    context.provide(ServiceKey("ocr.backend"), Backend())
'''
    bundle(
        archive,
        extra={"provides": {"host": {"ocr.backend": {"cardinality": "one"}}}, "contributes": {}},
        artifacts_extra={"python/plugin.py": code.encode()},
    )
    inspected = host.bootstrap["package_store"].inspect(archive)
    manager.install(archive, inspected["digest"], inspected["trust_modes"])
    with TestClient(app) as client:
        original = manager.plan(host.selected | {"ext.ocr", "provider.rapidocr"}, host.generation)
        manager.prepare(original["id"], original["digest"])
        manager.apply(original["id"], original["digest"])
        backend = host.require(ServiceKey("ocr.backend"))
        candidate = (host.selected - {"provider.rapidocr"}) | {"community.example"}
        response = client.post(
            "/api/plugins/plans",
            headers={"x-resume-token": "test"},
            json={
                "selected": sorted(candidate),
                "generation": host.generation,
            },
        )
        assert response.status_code == 200, response.text
        plan = response.json()
        assert "provider.rapidocr" in plan["removed"]
        assert "community.example" in plan["added"]
        assert "ext.ocr" in plan["affected"]
        assert host.require(ServiceKey("ocr.backend")) is backend
        manager.prepare(plan["id"], plan["digest"])
        manager.apply(plan["id"], plan["digest"])
        assert "ext.ocr" in host.selected
        assert "provider.rapidocr" not in host.selected
        result = host.require(ServiceKey("ocr")).read_document(
            Path("synthetic.png"), threading.Event()
        )
        assert result["text"] == "synthetic"
