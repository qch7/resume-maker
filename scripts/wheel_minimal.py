"""在仅安装系统依赖的解释器内验证实际制作、导出和恢复闭环"""

import importlib.util
import json
import sys
from io import BytesIO
from pathlib import Path
from threading import Event
from zipfile import ZipFile

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.domain.models import ResumeItem
from resume_maker.domain.resume import ResumeDocument
from resume_maker.infrastructure.storage import create_backup, restore_backup
from resume_maker.sdk.context import ServiceKey
from resume_maker.sdk.imports import ImportContext, ImportSource


def main():
    """无图片、PDF、OCR 和测试依赖时使用安装包的真实系统插件"""
    for name in ("PIL", "pymupdf", "pdf2docx", "rapidocr_onnxruntime", "httpx", "pytest"):
        assert importlib.util.find_spec(name) is None, name
    directory = Path.cwd() / "minimal-data"
    app = create_app(Config(data_dir=directory, profile="minimal"))
    host = app.state.runtime
    host.start()
    try:
        catalog = host.require(ServiceKey("catalog"))
        project = catalog.create_project("合成手工经历", [])
        catalog.put_draft(
            project["id"],
            project["head_revision"],
            "meta",
            {"description": "物理最小安装完成制作闭环"},
            0,
        )
        catalog.save_revision(project["id"], project["head_revision"], project["head_revision"])
        project = catalog.project(project["id"])
        resume = host.require(ServiceKey("resume")).save_resume(
            "合成简历",
            None,
            [
                ResumeItem(
                    project_id=project["id"], revision_id=project["head_revision"], highlight_ids=[]
                )
            ],
            document=ResumeDocument(
                personal={"name": "最小安装"},
                sections=[{"id": "projects", "kind": "projects", "title": "项目经历"}],
            ),
        )
        exported = host.require(ServiceKey("documents")).export(resume["id"])
        registry = host.require(ServiceKey("document.registry"))
        assert registry.importers("certificate") == []
        original = host.require(ServiceKey("assets")).read_file(
            f"exports/{exported['id']}", "resume.docx"
        )
        selected = registry.select_importer(ImportSource("resume.docx", original))
        stage = directory / "workspaces" / "minimal-import"
        stage.mkdir()
        result = registry.run_import(
            selected, ImportContext(stage, Event(), document_json=json.dumps(resume["document"]))
        )
        assert result.template.startswith(b"PK")
        assert selected.trace["id"] == "sys.docx/import"
        with ZipFile(BytesIO(original)) as archive:
            content = archive.read("word/document.xml").decode()
            assert "最小安装" in content and "物理最小安装完成制作闭环" in content
        backup = create_backup(host.require(ServiceKey("db")), directory)
        frontend = Config().frontend
        assert (frontend / "index.html").is_file()
        assert (frontend / "shared" / "react.js").is_file()
        assert all(name not in sys.modules for name in ("PIL", "pymupdf", "rapidocr_onnxruntime"))
    finally:
        host.close()
    restored_dir = Path.cwd() / "minimal-restored"
    restore_backup(backup, restored_dir)
    restored = create_app(Config(data_dir=restored_dir))
    try:
        exported = restored.state.runtime.require(ServiceKey("documents")).export(resume["id"])
        assert exported["manifest"]["items"][0]["revision_id"] == project["head_revision"]
    finally:
        restored.state.runtime.close()
    print("物理最小 wheel 验证通过：无可选依赖，手工编辑、固定版本、DOCX、备份恢复有效。")


if __name__ == "__main__":
    main()
