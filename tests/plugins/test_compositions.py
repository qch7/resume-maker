"""真实 HTTP 组合和最小产品闭环验收"""

from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.infrastructure.storage import restore_backup
from resume_maker.plugins.discovery import selection
from resume_maker.runtime.graph import PluginError, resolve

HEADERS = {"x-resume-token": "test"}


def test_minimal_manual_revision_docx_and_restore(tmp_path):
    """无 AI、源码、OCR 和 Word 时完成手工经历到备份恢复的闭环"""
    config = Config(data_dir=tmp_path / "data", profile="minimal", token="test")
    with TestClient(create_app(config)) as client:
        capabilities = client.get("/api/capabilities", headers=HEADERS).json()
        assert capabilities["ready"]
        assert len([key for key in capabilities["plugins"] if key.startswith("sys.")]) == 18
        assert "provider" not in capabilities["services"]
        assert client.get("/api/recruitment", headers=HEADERS).status_code == 404
        assert (
            client.post("/api/projects/scan", json={"path": "."}, headers=HEADERS).status_code
            == 405
        )
        project = client.post("/api/projects", json={"name": "手工经历"}, headers=HEADERS).json()
        second = client.post("/api/projects", json={"name": "另一段经历"}, headers=HEADERS).json()
        assert project["id"] != second["id"]
        body = {
            "base_revision": project["head_revision"],
            "field": "meta",
            "value": {"description": "使用本地资料完成独立验证"},
            "version": 0,
        }
        saved = client.put(f"/api/projects/{project['id']}/draft", json=body, headers=HEADERS)
        assert saved.status_code == 200, saved.text
        revision = client.post(
            f"/api/projects/{project['id']}/revisions",
            headers=HEADERS,
            json={
                "base_revision": project["head_revision"],
                "expected_head": project["head_revision"],
            },
        )
        assert revision.status_code == 200, revision.text
        detail = client.get(f"/api/projects/{project['id']}", headers=HEADERS).json()
        head = detail["project"]["head_revision"]
        document = {
            "personal": {"name": "合成测试"},
            "sections": [{"id": "projects", "title": "项目经历", "kind": "projects"}],
            "extensions": {
                "ext.example": {
                    "schema_version": 1,
                    "value": "保留值",
                    "display": {"title": "附加资料", "text": "保留值"},
                }
            },
        }
        resume = client.post(
            "/api/resumes",
            headers=HEADERS,
            json={
                "name": "最小组合",
                "items": [{"project_id": project["id"], "revision_id": head, "highlight_ids": []}],
                "document": document,
            },
        ).json()
        assert "id" in resume, resume
        exported = client.post(f"/api/resumes/{resume['id']}/exports", headers=HEADERS)
        assert exported.status_code == 200, exported.text
        assert exported.json()["pages"] is None
        output = client.get(f"/api/exports/{exported.json()['id']}/resume.docx", headers=HEADERS)
        assert output.status_code == 200
        assert output.content.startswith(b"PK")
        archive = client.post("/api/backups", headers=HEADERS)
        assert archive.status_code == 200, archive.text
        backup = tmp_path / "minimal.zip"
        backup.write_bytes(archive.content)
        state = client.get("/api/state", headers=HEADERS).json()
        assert state["conversations"] == state["honors"] == state["jobs"] == []
    target = tmp_path / "restored"
    restore_backup(backup, target)
    with TestClient(create_app(Config(data_dir=target, profile="minimal", token="test"))) as client:
        state = client.get("/api/state", headers=HEADERS).json()
        assert state["resumes"][0]["items"][0]["revision_id"] == head
        assert state["resumes"][0]["document"]["extensions"] == document["extensions"]
        response = client.post(f"/api/resumes/{resume['id']}/exports", headers=HEADERS)
        assert response.status_code == 200, response.text
        with ZipFile(target / "exports" / response.json()["id"] / "resume.docx") as archive:
            assert "合成测试" in archive.read("word/document.xml").decode()


@pytest.mark.parametrize("identifier", ["sys.privacy", "sys.sandbox", "sys.drafts", "sys.docx"])
def test_system_plugins_cannot_be_removed(identifier):
    """组合覆盖不能把必要保护或最小业务能力设为可选"""
    manifests, selected, required = selection("minimal")
    with pytest.raises(PluginError, match=identifier):
        resolve(manifests, selected - {identifier}, required)


def test_optional_reverse_dependencies_are_explicit():
    """关闭 AI 编排前必须处理所有硬依赖消费者，不能留半个可用界面"""
    manifests, selected, required = selection("standard")
    with pytest.raises(PluginError, match="provider"):
        resolve(manifests, selected - {"ext.ai-runtime"}, required)


@pytest.mark.parametrize("instances", [{"multiple": True}, {"scope": "task"}])
def test_unsupported_instance_lifetimes_never_silently_run_as_workspace(instances):
    """尚不支持的实例声明必须在导入入口前拒绝，不能悄悄共用工作区状态"""
    from resume_maker.sdk.manifest import Manifest

    manifests, selected, required = selection("minimal")
    manifest = Manifest(
        id="community.instances",
        title="合成实例",
        package="test",
        version="1.0.0",
        instances=instances,
    )
    manifests[manifest.id] = manifest
    with pytest.raises(PluginError, match="不支持的多实例或任务级实例"):
        resolve(manifests, selected | {manifest.id}, required)


def test_minimal_does_not_import_optional_modules(tmp_path):
    """新解释器确认最小启动无需导入 OCR、PDF、模型或模板实现"""
    import subprocess
    import sys

    script = "\n".join(
        [
            "import sys",
            "from pathlib import Path",
            "from resume_maker.api import create_app",
            "from resume_maker.core.config import Config",
            "app=create_app(Config(data_dir=Path(sys.argv[1]),profile='minimal'))",
            "blocked=('pymupdf','rapidocr_onnxruntime','resume_maker.integrations.providers.codex',"
            "'resume_maker.services.templates.tasks','resume_maker.services.honors')",
            "assert not any(key in sys.modules for key in blocked), "
            "sorted(set(blocked)&sys.modules.keys())",
            "app.state.runtime.close()",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(Path(tmp_path) / "minimal")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("identifier", sorted(selection("standard")[1] - selection("standard")[2]))
def test_each_optional_disable_has_explicit_dependency_or_working_minimal_core(
    identifier, tmp_path
):
    """逐项停用要么明确拒绝缺依赖组合，要么保留手工编辑及 DOCX 闭环"""
    from resume_maker.sdk.context import ServiceKey

    app = create_app(Config(data_dir=tmp_path, profile="standard", token="test"))
    host = app.state.runtime
    with TestClient(app) as client:
        selected = host.selected - {identifier}
        manager = host.require(ServiceKey("plugins"))
        try:
            resolve(host.manifests, selected, host.required)
        except PluginError:
            with pytest.raises(PluginError):
                manager.plan(sorted(selected), host.generation)
            assert host.generation == 1 and identifier in host.selected
            return
        plan = manager.plan(sorted(selected), host.generation)
        manager.prepare(plan["id"], plan["digest"])
        manager.apply(plan["id"], plan["digest"])
        assert identifier not in host.selected
        assert (
            client.post("/api/projects", headers=HEADERS, json={"name": "合成组合验证"}).status_code
            == 200
        )
        response = client.post(
            "/api/resumes",
            headers=HEADERS,
            json={
                "name": "合成组合",
                "items": [],
                "document": {
                    "personal": {"name": "Synthetic"},
                    "sections": [{"id": "projects", "title": "项目经历", "kind": "projects"}],
                },
            },
        )
        assert response.status_code == 200, response.text
        # 真实 Word 另行验证，此矩阵只检验引擎和组合边界
        from resume_maker.runtime.host import Contribution
        from resume_maker.sdk.documents import DocumentRenderer

        key = ("documents.renderers", "ext.word/default")
        if item := host.contributions.get(key):
            host.contributions[key] = Contribution(
                item.owner,
                item.point,
                item.identifier,
                DocumentRenderer("1.0.0", lambda *_: (None, "synthetic matrix")),
            )
        exported = client.post(f"/api/resumes/{response.json()['id']}/exports", headers=HEADERS)
        assert exported.status_code == 200, exported.text
        assert client.get(
            f"/api/exports/{exported.json()['id']}/resume.docx", headers=HEADERS
        ).content.startswith(b"PK")
