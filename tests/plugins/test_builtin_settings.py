"""验证内置运行配置真正进入实例和公开限制，兼容旧空配置"""

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from resume_maker.api.app import create_app
from resume_maker.core.config import Config
from resume_maker.integrations.document_limits import CERTIFICATE_MAX_BYTES, CERTIFICATE_MAX_PAGES
from resume_maker.plugin_packages.provider_rapidocr.configuration import Settings as OCRSettings
from resume_maker.plugin_packages.provider_rapidocr.local_ocr import LocalOCR
from resume_maker.plugins.discovery import discover
from resume_maker.runtime.configuration import compose_configuration, replacement_layer
from resume_maker.runtime.graph import PluginError
from resume_maker.sdk.model import ProviderError


def config_file(path, values):
    """通过用户实际使用的文件格式配置一组内置实例"""
    path.write_text(
        json.dumps(
            {
                "bundles": [
                    {
                        "name": "test",
                        "edits": [
                            {"instance": key, "operation": "set", "path": [field], "value": value}
                            for key, fields in values.items()
                            for field, value in fields.items()
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_runtime_settings_reach_consumers_and_survive_restart(tmp_path):
    """配置文件调整执行并发、数据库和日志，关闭后重启仍沿用保存的组合默认"""
    path = config_file(
        tmp_path / "policy.json",
        {
            "sys.jobs": {"max_workers": 2, "owner_close_timeout_seconds": 9},
            "provider.sqlite": {"lock_timeout_seconds": 0.5},
            "sys.activity": {
                "retention_days": 7,
                "max_records": 1234,
                "lock_timeout_seconds": 0.25,
            },
            "sys.plugins": {"plan_lifetime_seconds": 180, "install_timeout_seconds": 450},
        },
    )
    data = tmp_path / "data"
    for plugin_config in (path, None):
        app = create_app(Config(data_dir=data, profile="minimal", plugin_config=plugin_config))
        with TestClient(app):
            services = app.state.runtime.services
            assert services["tasks"].executor._max_workers == 2
            assert services["tasks"].policy.owner_close_timeout_seconds == 9
            with services["db"].connect() as connection:
                assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 500
            assert services["activity"].retention_days == 7
            assert services["activity"].max_records == 1234
            assert services["plugins"].policy.plan_lifetime_seconds == 180
            assert (
                app.state.runtime.bootstrap["environment_store"].policy.install_timeout_seconds
                == 450
            )


def test_upload_limits_and_retention_are_published_from_effective_policy(tmp_path):
    """导入能力和模板库通过真实 HTTP 返回后端限制及有效回收站策略"""
    path = config_file(
        tmp_path / "policy.json", {"ext.template-library": {"trash_retention_days": 7}}
    )
    app = create_app(Config(data_dir=tmp_path / "data", plugin_config=path))
    with TestClient(app) as client:
        headers = {"x-resume-token": app.state.runtime.bootstrap["config"].token}
        response = client.get("/api/document-importers?purpose=certificate", headers=headers)
        assert response.status_code == 200 and response.json()
        for importer in response.json():
            assert importer["limits"]["max_bytes"] == CERTIFICATE_MAX_BYTES
            assert importer["limits"]["max_pages"] == CERTIFICATE_MAX_PAGES
        response = client.get("/api/template-library", headers=headers)
        assert response.status_code == 200
        assert response.json()["trash_retention_days"] == 7


def test_ocr_instances_keep_their_own_engine_parameters_and_resolution(monkeypatch):
    """两个实例交错识别不会共享模型参数，复核关闭时只使用各自首次尺寸"""
    import rapidocr_onnxruntime

    calls, shapes = [], []

    def factory(**parameters):
        """以合成识别器记录真正传入引擎和推理的参数"""
        calls.append(parameters)

        def recognize(pixels):
            """返回固定坐标以验证不同实例的缩放输入"""
            shapes.append(pixels.shape)
            return [[[[0, 0], [50, 0], [50, 30], [0, 30]], "synthetic", 0.99]], []

        return recognize

    monkeypatch.setattr(rapidocr_onnxruntime, "RapidOCR", factory)
    first = LocalOCR(
        OCRSettings(intra_op_num_threads=4, base_side=512, adaptive_retry_enabled=False)
    )
    second = LocalOCR(
        OCRSettings(intra_op_num_threads=1, base_side=1024, adaptive_retry_enabled=False)
    )
    image = Image.new("RGB", (1600, 2400), "white")
    for backend in (first, second, first):
        assert backend.recognize(image, threading.Event())["blocks"][0]["text"] == "synthetic"
    assert [call["intra_op_num_threads"] for call in calls] == [4, 1]
    assert [shape[0] for shape in shapes] == [512, 1024, 512]
    first.close()
    assert first._engine is None and second._engine is not None
    with pytest.raises(ProviderError, match="已停止"):
        first.engine()


def test_old_empty_config_receives_schema_defaults_with_correct_provenance():
    """旧版本空配置补全为清单默认，未知输入不会被默认值吞掉"""
    manifests = discover()[0]
    result = compose_configuration(manifests, [replacement_layer("workspace", {"sys.jobs": {}})])
    assert result["configs"]["sys.jobs"]["max_workers"] == 4
    assert result["provenance"]["sys.jobs"]["/max_workers"] == "default"
    assert "" not in result["provenance"]["sys.jobs"]
    for value in (
        {"max_workers": 0},
        {"max_workers": True},
        {"max_workers": "4"},
        {"max_workers": 4.0},
        {"close_timeout_seconds": float("nan")},
        {"typo": 4},
    ):
        with pytest.raises(PluginError, match="sys.jobs"):
            compose_configuration(manifests, [replacement_layer("workspace", {"sys.jobs": value})])


def test_complete_example_is_valid_for_builtin_manifests():
    """示例中的每个实际字段都能被完整插件组合解析"""
    from resume_maker.runtime.configuration import startup_configuration

    path = Path(__file__).parents[2] / "examples/plugin-config.json"
    result = compose_configuration(discover()[0], startup_configuration({}, path))
    assert result["configs"]["ext.word"]["render_timeout_seconds"] == 90
    assert result["provenance"]["provider.rapidocr"]["/base_side"] == "bundle:runtime"


def test_word_timeout_and_preview_scale_reach_controlled_execution(tmp_path, monkeypatch):
    """真实执行入口传入配置等待并按配置栅格化，不启动桌面 Word"""
    import pymupdf

    from resume_maker.plugin_packages.ext_word.configuration import Settings
    from resume_maker.plugin_packages.ext_word.integrations.word import rendering
    from resume_maker.plugin_packages.ext_word.integrations.word.controlled import ControlledWord

    calls = []

    def execute(_grant, command, **options):
        """受控进程替身只输出一张合成 PDF 页面"""
        calls.append(options)
        with pymupdf.open() as document:
            document.new_page(width=80, height=100)
            document.save(command[6])

    monkeypatch.setattr(rendering, "os", SimpleNamespace(name="nt"))
    engine = ControlledWord(
        SimpleNamespace(execute=execute, revoke=lambda *_: None),
        SimpleNamespace(authorize=lambda *_, **__: "synthetic"),
        1,
        settings=Settings(render_timeout_seconds=120, preview_scale=2),
    )
    source, output = tmp_path / "source.docx", tmp_path / "output.pdf"
    assert engine.render(source, output) == (1, None)
    assert calls[0]["timeout"] == 120
    with Image.open(tmp_path / "page-1.png") as image:
        assert image.size == (160, 200)
    engine.close()


def test_management_policy_changes_require_host_restart(tmp_path):
    """管理器自身策略通过重启切换，不在活动下载和计划上替换等待规则"""
    app = create_app(Config(data_dir=tmp_path / "data", profile="minimal"))
    with TestClient(app):
        host = app.state.runtime
        manager = host.services["plugins"]
        plan = manager.plan(
            host.selected,
            host.generation,
            config_edits=[
                {
                    "instance": "sys.plugins",
                    "operation": "set",
                    "path": ["plan_lifetime_seconds"],
                    "value": 120,
                }
            ],
        )
        assert plan["mode"] == "host-restart"
        assert manager.policy.plan_lifetime_seconds == 600
