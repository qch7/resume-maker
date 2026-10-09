"""真实外部 OCR 提供方在同一计划替换，消费者和旧配置保持一致"""

import threading
from pathlib import Path

from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.sdk.context import ServiceKey
from tests.support.plugins import bundle


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
