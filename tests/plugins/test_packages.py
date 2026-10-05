"""外部包从检查到真实激活和卸载的完整行为"""

import hashlib
import json
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.runtime.graph import PluginError
from resume_maker.runtime.packages import PackageStore
from resume_maker.sdk.context import ServiceKey
from tests.support.plugins import bundle

HEADERS = {"x-resume-token": "test"}


def test_multiple_instances_persist_and_failed_health_restores_configuration(tmp_path):
    """真实外部包可创建独立实例，失败配置不影响另一实例或持久恢复点"""
    archive = tmp_path / "instances.rmp"
    code = '''from resume_maker.sdk.context import ServiceKey

def activate(context):
    """返回实例自己的配置，并在发布前拒绝负数"""
    value = context.config["count"]
    context.provide(ServiceKey("example"), {"value": value})
    context.rpc("value", lambda payload: value)
    context.rpc("load", lambda payload: context.data.get("count").value or 0)
    context.rpc("save", lambda payload: context.data.set(
        "count", payload, context.data.get("count").version
    ).value)
    def health():
        """模拟插件启动之后才能检测的故障"""
        if value < 0:
            raise RuntimeError("synthetic-health-failure")
    context.health(health)
'''
    bundle(
        archive,
        extra={
            "instances": {"multiple": True},
            "requires": {"host": {"storage.instances": ">=1.0.0 <2.0.0"}},
            "provides": {"host": {"example": {"cardinality": "many"}}},
            "contributes": {},
            "config": {"count": 1},
            "config_schema": {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
                "additionalProperties": False,
            },
            "rpc": {
                "load": {"input_schema": {"type": "null"}, "output_schema": {"type": "integer"}},
                "save": {"input_schema": {"type": "integer"}, "output_schema": {"type": "integer"}},
                "value": {"input_schema": {"type": "null"}, "output_schema": {"type": "integer"}},
            },
        },
        artifacts_extra={"python/plugin.py": code.encode()},
    )
    directory = tmp_path / "data"
    app = create_app(Config(data_dir=directory, token="test", profile="minimal"))
    host = app.state.runtime
    manager = host.require(ServiceKey("plugins"))
    inspection = host.bootstrap["package_store"].inspect(archive)
    manager.install(archive, inspection["digest"], set(inspection["trust_modes"]))
    specs = [{"id": f"community.{name}", "plugin": "community.example"} for name in ("one", "two")]
    with TestClient(app) as client:
        response = client.post(
            "/api/plugins/plans",
            headers=HEADERS,
            json={
                "generation": host.generation,
                "selected": sorted(host.selected | {"community.one", "community.two"}),
                "instances": specs,
                "configs": {"community.one": {"count": 7}, "community.two": {"count": 9}},
            },
        )
        assert response.status_code == 200, response.text
        plan = response.json()
        manager.prepare(plan["id"], plan["digest"])
        manager.apply(plan["id"], plan["digest"])
        untouched = host.instances["community.two"]
        for name, expected in (("one", 7), ("two", 9)):
            response = client.post(
                f"/api/plugins/rpc/community.{name}/value",
                headers=HEADERS,
                json={"generation": host.generation, "payload": None},
            )
            assert response.status_code == 200, response.text
            assert response.json() == expected
        with pytest.raises(PluginError, match="停用"):
            manager.uninstall("community.example")
        bad = {**host.configs, "community.one": {"count": -1}}
        plan = manager.plan(host.selected, host.generation, bad)
        manager.prepare(plan["id"], plan["digest"])
        with pytest.raises(Exception, match="已恢复"):
            manager.apply(plan["id"], plan["digest"])
        assert host.generation == 2
        assert host.instances["community.two"] is untouched
        assert host.service_values[("community.one", "example")]["value"] == 7
        entries = client.get("/api/capabilities", headers=HEADERS).json()["client"]
        one = next(item for item in entries if item["id"] == "community.one")
        assert one["plugin"] == "community.example"
        assert one["entry"]["entry"].startswith("/plugin-assets/community.example/")
        loaded = client.get(one["entry"]["entry"])
        assert loaded.status_code == 200, loaded.text
        assert loaded.content == b"export function activate(context) {}"
        for name, value in (("one", 11), ("two", 22)):
            response = client.post(
                f"/api/plugins/rpc/community.{name}/save",
                headers=HEADERS,
                json={"generation": host.generation, "payload": value},
            )
            assert response.status_code == 200 and response.json() == value
    restored = create_app(Config(data_dir=directory, token="test"))
    try:
        assert restored.state.runtime.service_values[("community.one", "example")]["value"] == 7
        assert restored.state.runtime.service_values[("community.two", "example")]["value"] == 9
        assert restored.state.runtime.instances["community.one"].data.get("count").value == 11
        assert restored.state.runtime.instances["community.two"].data.get("count").value == 22
    finally:
        restored.state.runtime.close()


def test_worker_uses_prepared_offline_environment(tmp_path):
    """插件专用依赖只装入候选解释器，重启后真实 worker 能导入它"""
    from io import BytesIO

    wheel = BytesIO()
    with ZipFile(wheel, "w") as archive:
        archive.writestr("synthetic_plugin_math.py", "def double(value):\n    return value * 2\n")
        archive.writestr(
            "synthetic_plugin_math-1.0.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: synthetic-plugin-math\nVersion: 1.0.0\n",
        )
        archive.writestr(
            "synthetic_plugin_math-1.0.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: synthetic\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr("synthetic_plugin_math-1.0.0.dist-info/RECORD", "")
    raw = wheel.getvalue()
    wheel_name = "wheels/synthetic_plugin_math-1.0.0-py3-none-any.whl"
    specification = {
        "version": 1,
        "wheels": [
            {
                "name": "synthetic-plugin-math",
                "version": "1.0.0",
                "file": wheel_name,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        ],
    }
    package = tmp_path / "environment.rmp"
    bundle(
        package,
        worker=True,
        extra={
            "dependencies": ["synthetic-plugin-math==1.0.0"],
            "environment_lock": "environment.json",
        },
        artifacts_extra={
            wheel_name: raw,
            "environment.json": json.dumps(specification).encode(),
            "python/worker.py": (
                b"import json,sys,synthetic_plugin_math as m\nr=json.load(sys.stdin)\n"
                b"print(json.dumps({'rpc_version':1,'id':r['id'],"
                b"'result':m.double(r['payload'])}))"
            ),
        },
    )
    directory = tmp_path / "data"
    app = create_app(Config(data_dir=directory, token="test", profile="minimal"))
    with TestClient(app) as client:
        store = app.state.runtime.bootstrap["package_store"]
        checked = store.inspect(package)
        app.state.services.plugins.install(package, checked["digest"], checked["trust_modes"])
        response = client.post(
            "/api/plugins/packages/community.example/environment", headers=HEADERS
        )
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "ready"
        from pathlib import Path

        assert not Path(response.json()["python"]).is_symlink()
        assert app.state.runtime.missing_dependencies("community.example")
    restored = create_app(Config(data_dir=directory, token="test"))
    with TestClient(restored) as client:
        enable(client, "community.example")
        response = client.post(
            "/api/plugins/rpc/community.example/double",
            headers=HEADERS,
            json={"generation": restored.state.runtime.generation, "payload": 21},
        )
        assert response.status_code == 200, response.text
        assert response.json() == 42


def enable(client, identifier):
    """使用用户可见的三阶段管理 API 激活已安装扩展"""
    capabilities = client.get("/api/capabilities", headers=HEADERS).json()
    plan = client.post(
        "/api/plugins/plans",
        headers=HEADERS,
        json={
            "selected": [*capabilities["plugins"], identifier],
            "generation": capabilities["generation"],
        },
    ).json()
    path = f"/api/plugins/plans/{plan['id']}"
    assert (
        client.post(path + "/prepare", headers=HEADERS, json={"digest": plan["digest"]}).status_code
        == 200
    )
    response = client.post(path + "/apply", headers=HEADERS, json={"digest": plan["digest"]})
    assert response.status_code == 200, response.text


def test_external_resume_source_survives_disable_and_restart(tmp_path):
    """外部来源通过真实接口采用、同步和导出，停用前保留最后确认内容"""
    archive = tmp_path / "source.rmp"
    code = '''from resume_maker.sdk.sources import ResumeSource, SourceItem, SourcePage

def activate(context):
    """注册不依赖源码或荣誉库的合成资料来源"""
    def item(reader):
        """在当前事务读取已确认内容"""
        return SourceItem(id="synthetic", version="1",
            title=reader.setting("community.example:title", "初始合成资料"))
    def browse(reader, cursor, query, limit):
        """提供一个有界页面"""
        return SourcePage(items=(item(reader),))
    def resolve(reader, identifiers):
        """只返回明确关联的条目"""
        return (item(reader),) if "synthetic" in identifiers else ()
    context.contribute("resume.sources", "community.example/source",
        ResumeSource("合成资料来源", "1.0.0", browse, resolve))
'''
    bundle(
        archive,
        extra={
            "contributes": {"resume.sources": ["community.example/source"]},
            "provides": {},
            "rpc": {},
        },
        artifacts_extra={"python/plugin.py": code.encode()},
    )
    config = Config(data_dir=tmp_path / "data", token="test", profile="minimal")
    app = create_app(config)
    with TestClient(app) as client:
        store = app.state.runtime.bootstrap["package_store"]
        checked = store.inspect(archive)
        app.state.services.plugins.install(archive, checked["digest"], checked["trust_modes"])
        enable(client, "community.example")
        assert (
            client.get("/api/resume-sources", headers=HEADERS).json()[0]["title"] == "合成资料来源"
        )
        response = client.get(
            "/api/resume-source-items",
            headers=HEADERS,
            params={"provider": "community.example/source"},
        )
        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        document = {
            "personal": {"name": "合成用户"},
            "sections": [
                {"id": "projects", "kind": "projects", "title": "项目"},
                {
                    "id": "notes",
                    "title": "资料",
                    "entries": [
                        {
                            "id": "entry",
                            "title": item["title"],
                            "source": {
                                "provider": "community.example/source",
                                "id": item["id"],
                                "version": item["version"],
                            },
                        }
                    ],
                },
            ],
        }
        saved = client.post(
            "/api/resumes",
            headers=HEADERS,
            json={"name": "来源简历", "items": [], "document": document},
        )
        assert saved.status_code == 200, saved.text
        resume_id = saved.json()["id"]
        app.state.services.db.set_setting("community.example:title", "最后确认内容")
        state = client.get("/api/state", headers=HEADERS).json()
        assert (
            state["resumes"][0]["document"]["sections"][1]["entries"][0]["title"] == "最后确认内容"
        )
        host = app.state.runtime
        manager = app.state.services.plugins
        plan = manager.plan(host.selected - {"community.example"}, host.generation)
        assert "sys.resume" in plan["affected"]
        manager.prepare(plan["id"], plan["digest"])
        manager.apply(plan["id"], plan["digest"])
        assert client.get("/api/resume-sources", headers=HEADERS).json() == []
        exported = client.post(f"/api/resumes/{resume_id}/exports", headers=HEADERS)
        assert exported.status_code == 200, exported.text
        snapshot = exported.json()["manifest"]["resume"]["document"]
        assert snapshot["sections"][1]["entries"][0]["title"] == "最后确认内容"
    with TestClient(create_app(Config(data_dir=config.data_dir, token="test"))) as client:
        state = client.get("/api/state", headers=HEADERS).json()
        assert (
            state["resumes"][0]["document"]["sections"][1]["entries"][0]["title"] == "最后确认内容"
        )


def test_external_document_engine_uses_frozen_input_and_keeps_history_after_disable(tmp_path):
    """外部引擎无需修改主工程即可导出，停用拒绝重新生成但历史文件仍可读取"""
    archive = tmp_path / "engine.rmp"
    code = '''from docx import Document
from resume_maker.sdk.documents import DocumentEngine

def activate(context):
    """注册仅接收固定资料的合成文档引擎"""
    def generate(output, inputs):
        """用测试文字证明明确选中了外部引擎"""
        resume, projects, template = inputs.values()
        document = Document()
        document.add_paragraph(
            "synthetic external engine " + resume["document"]["personal"]["name"]
        )
        document.save(output)
    context.contribute(
        "documents.engines", "community.example/docx", DocumentEngine("1.0.0", generate)
    )
'''
    bundle(
        archive,
        extra={
            "provides": {},
            "requires": {"host": {"documents": ">=1.0.0 <2.0.0"}},
            "enhances": ["documents"],
            "contributes": {"documents.engines": ["community.example/docx"]},
        },
        artifacts_extra={"python/plugin.py": code.encode()},
    )
    app = create_app(Config(data_dir=tmp_path / "data", token="test", profile="minimal"))
    manager = app.state.runtime.require(ServiceKey("plugins"))
    inspected = app.state.runtime.bootstrap["package_store"].inspect(archive)
    manager.install(archive, inspected["digest"], set(inspected["trust_modes"]))
    with TestClient(app) as client:
        enable(client, "community.example")
        entries = client.get("/api/document-engines", headers=HEADERS).json()
        assert {row["id"] for row in entries["engines"]} == {
            "sys.docx/default",
            "community.example/docx",
        }
        resume = client.post(
            "/api/resumes",
            headers=HEADERS,
            json={
                "name": "合成引擎验证",
                "items": [],
                "document": {
                    "personal": {"name": "Synthetic"},
                    "sections": [{"id": "projects", "title": "项目经历", "kind": "projects"}],
                },
            },
        ).json()
        path = f"/api/resumes/{resume['id']}/exports?engine_id=community.example/docx"
        response = client.post(path, headers=HEADERS)
        assert response.status_code == 200, response.text
        record = response.json()
        assert record["manifest"]["engine"] == {"id": "community.example/docx", "version": "1.0.0"}
        from io import BytesIO

        download = f"/api/exports/{record['id']}/resume.docx"
        with ZipFile(BytesIO(client.get(download, headers=HEADERS).content)) as document:
            assert b"synthetic external engine Synthetic" in document.read("word/document.xml")
        preview = client.post(
            "/api/resume-previews?engine_id=community.example/docx",
            headers=HEADERS,
            json={"document": resume["document"], "items": []},
        )
        assert preview.status_code == 200, preview.text
        plan = manager.plan(
            sorted(app.state.runtime.selected - {"community.example"}), app.state.runtime.generation
        )
        manager.prepare(plan["id"], plan["digest"])
        manager.apply(plan["id"], plan["digest"])
        assert client.post(path, headers=HEADERS).status_code == 409
        assert client.get(download, headers=HEADERS).status_code == 200


def test_external_host_and_client_install_without_rebuilding(tmp_path):
    """外部预构建包通过正常管理流程装载，客户端 URL 固定到摘要"""
    archive = tmp_path / "example.rmp"
    contributions = {
        "http.routes": ["example/routes"],
        "commands": ["community.example/open"],
        "resume.field_editors": ["community.example/fields"],
        "workflow.steps": ["community.example/step"],
        "workflow.state_contributors": ["community.example/state"],
    }
    bundle(archive, extra={"contributes": contributions})
    app = create_app(Config(data_dir=tmp_path / "data", token="test", profile="minimal"))
    with TestClient(app) as client:
        inspection = client.post(
            "/api/plugins/packages/inspect", headers=HEADERS, json={"path": str(archive)}
        ).json()
        assert "example" not in app.state.runtime.services
        body = {
            "path": str(archive),
            "digest": inspection["digest"],
            "trusted_modes": inspection["trust_modes"],
        }
        assert (
            client.post("/api/plugins/packages/install", headers=HEADERS, json=body).status_code
            == 200
        )
        assert "example" not in app.state.runtime.services
        enable(client, "community.example")
        assert client.get("/api/plugins/community.example/hello", headers=HEADERS).json() == {
            "message": "external plugin works"
        }
        capabilities = client.get("/api/capabilities", headers=HEADERS).json()
        assert (
            next(
                row["contributes"]
                for row in capabilities["client"]
                if row["id"] == "community.example"
            )
            == contributions
        )
        entry = next(
            row["entry"]["entry"]
            for row in capabilities["client"]
            if row["id"] == "community.example"
        )
        assert inspection["digest"] in entry
        assert client.get(entry).status_code == 200
        assert client.get(entry.replace("client/index.js", "python/plugin.py")).status_code == 404
        assert (
            client.delete("/api/plugins/packages/community.example", headers=HEADERS).status_code
            == 409
        )


def test_worker_process_validates_dto_and_reaps_process(tmp_path):
    """受信任 worker 在独立进程执行计算，通过同一执行和 sandbox 服务回收"""
    archive = tmp_path / "worker.rmp"
    bundle(archive, worker=True)
    app = create_app(Config(data_dir=tmp_path / "data", token="test", profile="minimal"))
    store = app.state.runtime.bootstrap["package_store"]
    manager = app.state.runtime.require(ServiceKey("plugins"))
    inspection = store.inspect(archive)
    manager.install(archive, inspection["digest"], {"worker"})
    with TestClient(app) as client:
        enable(client, "community.example")
        worker = app.state.runtime.require(ServiceKey("example"))
        assert worker.call("double", 21) == 42
        assert worker.active == set()
        with pytest.raises(Exception, match="integer"):
            worker.call("double", "invalid")
        result = client.post(
            "/api/plugins/rpc/community.example/double",
            headers=HEADERS,
            json={"generation": 2, "payload": 21},
        )
        assert result.status_code == 200 and result.json() == 42
        assert (
            client.post(
                "/api/plugins/rpc/community.example/double",
                headers=HEADERS,
                json={"generation": 1, "payload": 21},
            ).status_code
            == 409
        )


def test_restore_without_external_code_keeps_desired_selection(tmp_path):
    """备份不携带代码，恢复后仍可使用最小系统并保留缺包选择及资料"""
    from resume_maker.infrastructure.storage import create_backup, restore_backup

    archive = tmp_path / "example.rmp"
    bundle(archive)
    app = create_app(Config(data_dir=tmp_path / "data", token="test", profile="minimal"))
    manager = app.state.runtime.require(ServiceKey("plugins"))
    inspected = app.state.runtime.bootstrap["package_store"].inspect(archive)
    manager.install(archive, inspected["digest"], set(inspected["trust_modes"]))
    with TestClient(app) as client:
        enable(client, "community.example")
        app.state.services.db.set_setting("community.example:value", {"retained": True})
        backup = create_backup(app.state.services.db, tmp_path / "data")
    target = tmp_path / "restored"
    restore_backup(backup, target)
    restored = create_app(Config(data_dir=target, token="test"))
    with TestClient(restored) as client:
        state = client.get("/api/plugins", headers=HEADERS).json()
        assert "community.example" in state["desired"]
        assert "community.example" in state["blocked"]
        assert restored.state.services.db.setting("community.example:value") == {"retained": True}
        assert (
            client.post(
                "/api/projects", headers=HEADERS, json={"name": "恢复后手工经历"}
            ).status_code
            == 200
        )
    again = create_app(Config(data_dir=target, token="test"))
    assert "community.example" in again.state.runtime.desired
    again.state.runtime.close()


def test_external_config_is_validated_and_applied_with_generation(tmp_path):
    """无效配置不能进入激活，合法替换生成新的配置快照并跨重启保留"""
    archive = tmp_path / "example.rmp"
    bundle(
        archive,
        extra={
            "config": {"count": 1},
            "config_schema": {
                "type": "object",
                "properties": {"count": {"type": "integer", "minimum": 1}},
                "required": ["count"],
                "additionalProperties": False,
            },
        },
    )
    app = create_app(Config(data_dir=tmp_path / "data", token="test", profile="minimal"))
    manager = app.state.runtime.require(ServiceKey("plugins"))
    inspected = app.state.runtime.bootstrap["package_store"].inspect(archive)
    manager.install(archive, inspected["digest"], set(inspected["trust_modes"]))
    with TestClient(app) as client:
        enable(client, "community.example")
        selected = sorted(app.state.runtime.selected)
        with pytest.raises(PluginError, match="schema"):
            manager.plan(selected, 2, {"community.example": {"count": 0}})
        plan = manager.plan(selected, 2, {"community.example": {"count": 3}})
        manager.prepare(plan["id"], plan["digest"])
        manager.apply(plan["id"], plan["digest"])
        assert app.state.runtime.instances["community.example"].config == {"count": 3}
    restored = create_app(Config(data_dir=tmp_path / "data"))
    assert restored.state.runtime.instances["community.example"].config == {"count": 3}
    restored.state.runtime.close()


@pytest.mark.parametrize("instance", ["community.example", "community.one"])
@pytest.mark.parametrize("entry", ["client/index.js", "index.js"])
def test_isolated_client_uses_opaque_sandbox_and_no_instance_token(tmp_path, instance, entry):
    """隔离页面仅公开端口握手，CSP 禁止资料网络访问且不注入实例凭据"""
    archive = tmp_path / "example.rmp"
    bundle(
        archive,
        extra={
            "instances": {"multiple": True},
            "entrypoints": {"client": {"mode": "isolated-client", "entry": entry}},
            "provides": {},
            "contributes": {},
        },
        artifacts_extra={entry: b"export function activate(context) {}"},
    )
    app = create_app(
        Config(data_dir=tmp_path / "data", token="synthetic-ui-token", profile="minimal")
    )
    manager = app.state.runtime.require(ServiceKey("plugins"))
    inspected = app.state.runtime.bootstrap["package_store"].inspect(archive)
    manager.install(archive, inspected["digest"], {"isolated-client"})
    plan = manager.plan(
        [*app.state.runtime.selected, instance],
        1,
        instances=[{"id": instance, "plugin": "community.example"}],
    )
    manager.prepare(plan["id"], plan["digest"])
    manager.apply(plan["id"], plan["digest"])
    with TestClient(app) as client:
        response = client.get(f"/plugin-ui/community.example/{inspected['digest']}")
        assert response.status_code == 200
        policy = response.headers["content-security-policy"]
        assert "sandbox allow-scripts;" in policy and "allow-same-origin" not in policy
        assert "connect-src 'none'" in policy
        assert "synthetic-ui-token" not in response.text
        entry = f"/plugin-assets/community.example/{inspected['digest']}/{entry}"
        assert entry in response.text
        assert client.get(entry).status_code == 200
        plan = manager.plan(app.state.runtime.selected - {instance}, app.state.runtime.generation)
        manager.prepare(plan["id"], plan["digest"])
        manager.apply(plan["id"], plan["digest"])
        assert client.get(entry).status_code == 404
        assert client.get(f"/plugin-ui/community.example/{inspected['digest']}").status_code == 404


@pytest.mark.parametrize("entry", ["index.js", "client/index.js"])
def test_trusted_client_entry_at_package_root_or_subdirectory_is_downloadable(tmp_path, entry):
    """实际提交可信客户端后下载入口及相邻资源，包元数据仍不可公开"""
    archive = tmp_path / "client.rmp"
    parent = entry.rpartition("/")[0]
    stylesheet = f"{parent}/style.css" if parent else "style.css"
    code = b"export function activate(context) {}"
    bundle(
        archive,
        extra={
            "entrypoints": {"client": {"mode": "trusted-client", "entry": entry}},
            "provides": {},
            "contributes": {},
        },
        artifacts_extra={entry: code, stylesheet: b".synthetic { color: blue; }"},
    )
    app = create_app(Config(data_dir=tmp_path / "data", token="test", profile="minimal"))
    with TestClient(app) as client:
        manager = app.state.services.plugins
        inspected = app.state.runtime.bootstrap["package_store"].inspect(archive)
        manager.install(archive, inspected["digest"], {"trusted-client"})
        enable(client, "community.example")
        entries = client.get("/api/capabilities", headers=HEADERS).json()["client"]
        descriptor = next(item for item in entries if item["id"] == "community.example")
        response = client.get(descriptor["entry"]["entry"])
        assert response.status_code == 200 and response.content == code
        base = f"/plugin-assets/community.example/{inspected['digest']}/"
        assert client.get(base + stylesheet).status_code == 200
        assert client.get(base + "manifest.json").status_code == 404


def test_inspect_rejects_hash_mismatch_and_identity_conflict(tmp_path):
    """未执行任何入口前拒绝损坏产物和伪装系统身份"""
    archive = tmp_path / "plugin.rmp"
    bundle(archive, extra={"id": "sys.privacy"})
    store = PackageStore(tmp_path / "data", set())
    with pytest.raises(PluginError, match="系统"):
        store.inspect(archive)
    bundle(archive)
    with ZipFile(archive) as source:
        files = {name: source.read(name) for name in source.namelist()}
    files["client/index.js"] = b"changed"
    with ZipFile(archive, "w") as target:
        for name, data in files.items():
            target.writestr(name, data)
    with pytest.raises(PluginError, match="摘要"):
        store.inspect(archive)


def test_external_importer_full_upload_template_cancel_disable_restore(tmp_path):
    """真实外部格式接入两条导入路径，任务排空、停用和恢复均保留原件及处理记录"""
    import base64
    from io import BytesIO

    from PIL import Image

    from resume_maker.core.errors import Problem
    from resume_maker.infrastructure.storage import restore_backup
    from resume_maker.plugins.discovery import selection
    from tests.support.templates import (
        TemplateProvider,
        completed,
        simple_document,
        simple_template,
    )

    png = BytesIO()
    Image.new("RGB", (10, 10), "white").save(png, format="PNG")
    code = '''import base64
from resume_maker.sdk.imports import DocumentImporter, ImportProbe, ImportResult

PAGE = base64.b64decode("PNG_BASE64")

def probe(source):
    """自定义格式以实际文件头识别，两种用途分别声明页数"""
    if source.data.startswith(b"SYNTHETIC:"):
        return ImportProbe("synthetic", 2 if source.purpose == "certificate" else None)
    return None

def prepare(source, context):
    """通过公开协议返回字节，不接触主项目目录或业务数据库"""
    if source.purpose == "certificate":
        return ImportResult(pages=(PAGE,) if source.data.endswith(b"partial") else (PAGE, PAGE))
    return ImportResult(template=source.data.removeprefix(b"SYNTHETIC:"))

def activate(context):
    """提供两个同格式处理器以验证明确选择，生命周期由消费声明自动连接"""
    for identifier in ("first", "second"):
        context.contribute("documents.importers", "community.example/" + identifier,
            DocumentImporter("1.0.0", "合成格式 " + identifier,
                ("template", "certificate"), (".synthetic",), probe, prepare))
'''.replace("PNG_BASE64", base64.b64encode(png.getvalue()).decode())
    archive = tmp_path / "importer.rmp"
    bundle(
        archive,
        extra={
            "entrypoints": {"host": {"mode": "trusted-host", "entry": "python/plugin.py:activate"}},
            "provides": {},
            "contributes": {
                "documents.importers": ["community.example/first", "community.example/second"]
            },
        },
        artifacts_extra={"python/plugin.py": code.encode()},
    )
    selected = selection("minimal")[1] | {
        "ext.honors",
        "ext.template-adapter",
        "ext.template-ai",
        "ext.ai-runtime",
        "ext.provider-codex",
    }
    config = Config(data_dir=tmp_path / "data", plugins=tuple(selected), token="test")
    with TemplateProvider(block=True) as provider:
        app = create_app(config, provider)
        manager = app.state.runtime.require(ServiceKey("plugins"))
        inspected = app.state.runtime.bootstrap["package_store"].inspect(archive)
        manager.install(archive, inspected["digest"], set(inspected["trust_modes"]))
        with TestClient(app) as client:
            enable(client, "community.example")
            entries = client.get(
                "/api/document-importers?purpose=certificate", headers=HEADERS
            ).json()
            assert {row["id"] for row in entries} == {
                "community.example/first",
                "community.example/second",
            }
            upload = "/api/honors/upload?filename=certificate.synthetic"
            assert (
                client.post(upload, content=b"SYNTHETIC:example", headers=HEADERS).status_code
                == 409
            )
            upload += "&importer_id=community.example/first"
            response = client.post(upload, content=b"SYNTHETIC:example", headers=HEADERS)
            assert response.status_code == 201, response.text
            honor = response.json()
            assert honor["attachment"]["pages"] == 2
            trace = honor["attachment"]["importer"]
            assert trace["artifact_sha256"] == inspected["digest"]
            assert trace["source_sha256"] == hashlib.sha256(b"SYNTHETIC:example").hexdigest()
            assert (
                client.post(upload, content=b"SYNTHETIC:partial", headers=HEADERS).status_code
                == 409
            )
            assert len(client.get("/api/honors", headers=HEADERS).json()) == 1
            original = f"/api/honors/{honor['id']}/original"
            assert client.get(original, headers=HEADERS).content == b"SYNTHETIC:example"
            assert (
                client.get(f"/api/honors/{honor['id']}/pages/2", headers=HEADERS).content
                == png.getvalue()
            )

            source = tmp_path / "template.docx"
            simple_template(source)
            custom = tmp_path / "template.synthetic"
            raw = b"SYNTHETIC:" + source.read_bytes()
            custom.write_bytes(raw)
            body = {"path": str(custom), "document": simple_document().model_dump(), "items": []}
            assert (
                client.post("/api/templates/analyses", json=body, headers=HEADERS).status_code
                == 409
            )
            body["importer_id"] = "community.example/first"
            response = client.post("/api/templates/analyses", json=body, headers=HEADERS)
            assert response.status_code == 200, response.text
            task_id = response.json()["id"]
            assert provider.started.wait(10)
            custom.write_bytes(b"source changed after task started")
            plan = manager.plan(sorted(selected), app.state.runtime.generation)
            assert {"sys.documents", "ext.honors", "ext.template-ai"} <= set(plan["affected"])
            manager.prepare(plan["id"], plan["digest"])
            with pytest.raises(Problem):
                manager.apply(plan["id"], plan["digest"])
            manager.cancel_tasks(plan["id"], plan["digest"])
            with pytest.raises(Problem):
                manager.apply(plan["id"], plan["digest"])
            provider.release.set()
            task = completed(app.state.services.templates, task_id)
            assert task["status"] == "cancelled"
            manager.apply(plan["id"], plan["digest"])
            assert client.get(original, headers=HEADERS).content == b"SYNTHETIC:example"
            retry = f"/api/templates/analyses/{task_id}/retry"
            retry_body = {"document": simple_document().model_dump(), "items": []}
            assert client.post(retry, json=retry_body, headers=HEADERS).status_code == 409
            enable(client, "community.example")
            provider.block = False
            response = client.post(retry, json=retry_body, headers=HEADERS)
            assert response.status_code == 200, response.text
            retried = completed(app.state.services.templates, response.json()["id"])
            assert retried["status"] == "completed", retried
            assert retried["importer"] == task["importer"]
            assert retried["importer"]["source_sha256"] == hashlib.sha256(raw).hexdigest()
            assert not list((config.data_dir / "workspaces").glob("certificate-import-*"))
            response = client.post("/api/backups", headers=HEADERS)
            assert response.status_code == 200, response.text
            backup = tmp_path / "backup.zip"
            backup.write_bytes(response.content)
    restored = tmp_path / "restored"
    restore_backup(backup, restored)
    with TestClient(
        create_app(
            Config(data_dir=restored, plugins=tuple(selected), token="test"), TemplateProvider()
        )
    ) as client:
        assert client.get(original, headers=HEADERS).content == b"SYNTHETIC:example"
        saved = client.get("/api/honors", headers=HEADERS).json()[0]
        assert saved["attachment"]["importer"] == trace
        restored_task = client.get(
            f"/api/templates/analyses/{retried['id']}", headers=HEADERS
        ).json()
        assert restored_task["importer"] == retried["importer"]
