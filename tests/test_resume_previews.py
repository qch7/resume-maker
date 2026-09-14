"""当前模板预览的草稿隔离、缓存、重试和文件访问边界。"""

from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from test_template_mapping import make_template, resume_content

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.domain.models import ResumeItem
from resume_maker.infrastructure.database import dump, now
from resume_maker.integrations.sources import digest
from resume_maker.services import resume_previews
from resume_maker.services.documents import Documents
from resume_maker.services.resume_previews import ResumePreviews


def register_template(catalog, data_dir):
    """登记脱敏的真实完整映射，不经过 AI 或用户数据目录。"""
    path = data_dir / "templates" / "mapped" / "template.docx"
    path.parent.mkdir(parents=True)
    _, plan = make_template(path)
    with catalog.db.transaction() as conn:
        conn.execute(
            "INSERT INTO templates VALUES (?,?,?,?,?)",
            (
                "mapped",
                "测试模板",
                digest(path.read_bytes()),
                dump({"plan": plan.model_dump()}),
                now(),
            ),
        )
    return path


@pytest.fixture
def preview(catalog, tmp_path, monkeypatch):
    """模拟排版软件的文件输出，仍使用真实 DOCX 填充器。"""
    calls = []

    def render(source, output):
        """记录排版次数并建立可下载文件，避免单元测试启动 Word。"""
        calls.append(source)
        output.write_bytes(b"pdf")
        (output.parent / "page-1.png").write_bytes(b"png")
        return 1, None

    monkeypatch.setattr("resume_maker.services.resume_previews.render_word", render)
    register_template(catalog, tmp_path / "data")
    service = ResumePreviews(catalog, tmp_path / "data")
    yield service, calls
    service.stop()


def test_current_template_uses_unsaved_content_without_publishing(
    preview, catalog, project, populated, tmp_path
):
    """未保存的个人资料和经历进入模板，正式版本、草稿、方案与导出记录均不被改写。"""
    service, calls = preview
    document = resume_content().model_dump()
    document["personal"]["name"] = "尚未保存的姓名"
    working = deepcopy(populated["content"])
    working["title"] = "尚未提交的项目"
    working["highlights"][0]["text"] = "当前正在输入的亮点"
    catalog.put_draft(project["id"], populated["id"], "experience", working, 0)
    before = {
        table: catalog.db.all(f"SELECT * FROM {table}")
        for table in ("drafts", "revisions", "resumes", "exports")
    }
    items = [
        {
            "project_id": project["id"],
            "revision_id": populated["id"],
            "highlight_ids": ["one"],
            "content": working,
        }
    ]
    result = service.render("mapped", document, items)
    output = service.file(result["id"], "resume.docx")
    with (
        ZipFile(output) as archive,
        ZipFile(tmp_path / "data/templates/mapped/template.docx") as source,
    ):
        xml = archive.read("word/document.xml").decode()
        assert "尚未保存的姓名" in xml
        assert "尚未提交的项目" in xml
        assert "当前正在输入的亮点" in xml
        assert "Export Word" not in xml
        assert archive.read("word/styles.xml") == source.read("word/styles.xml")
    assert before == {table: catalog.db.all(f"SELECT * FROM {table}") for table in before}
    assert len(calls) == 1
    assert service.file(result["id"], "page-1.png").is_file()
    for filename in ("template.docx", "page-0.png", "page-2.png", "../template.docx"):
        with pytest.raises(Problem, match="不存在"):
            service.file(result["id"], filename)
    assert service.render("mapped", document, items) == result
    assert len(calls) == 1
    document["personal"]["name"] = "继续输入的姓名"
    assert service.render("mapped", document, items)["id"] != result["id"]
    items[0]["highlight_ids"] = ["two"]
    assert service.render("mapped", document, items)["id"] != result["id"]
    assert len(calls) == 3


def test_complete_template_preview_matches_formal_export(
    preview, catalog, project, populated, tmp_path, monkeypatch
):
    """完整模板的预览与正式导出具有相同内容和版式，关闭只回收临时预览。"""
    service, _ = preview
    documents = Documents(catalog, tmp_path / "data")
    document = resume_content()
    item = ResumeItem(project_id=project["id"], revision_id=populated["id"], highlight_ids=["two"])
    result = service.render("mapped", document.model_dump(), [item.model_dump()])
    resume = catalog.save_resume("固定方案", "mapped", [item], document=document)
    monkeypatch.setattr(
        "resume_maker.services.documents.render_word", lambda *_: (None, "No renderer")
    )
    exported = documents.export(resume["id"])
    with (
        ZipFile(service.file(result["id"], "resume.docx")) as left,
        ZipFile(tmp_path / "data/exports" / exported["id"] / "resume.docx") as right,
    ):
        assert left.namelist() == right.namelist()
        assert all(left.read(name) == right.read(name) for name in left.namelist())
    workspace = Path(service.directory.name)
    service.stop()
    assert not workspace.exists()
    assert (tmp_path / "data/templates/mapped/template.docx").is_file()
    assert (tmp_path / "data/exports" / exported["id"] / "resume.docx").is_file()


def test_failed_render_can_download_word_and_retry(preview, monkeypatch):
    """Word 不可用时仍提供试填文件，但失败不能缓存成永久结果。"""
    service, _ = preview
    renderer = resume_previews.render_word
    monkeypatch.setattr(
        "resume_maker.services.resume_previews.render_word", lambda *_: (None, "Word unavailable")
    )
    result = service.render("mapped", resume_content().model_dump(), [])
    assert service.file(result["id"], "resume.docx").is_file()
    with pytest.raises(Problem, match="不存在"):
        service.file(result["id"], "resume.pdf")
    monkeypatch.setattr("resume_maker.services.resume_previews.render_word", renderer)
    retry = service.render("mapped", resume_content().model_dump(), [])
    assert retry["id"] != result["id"]
    assert retry["pages"] == 1


def test_rejects_invalid_references_and_changed_template(preview, project, populated):
    """缓存不能绕过模板哈希、项目归属和选中亮点的核验。"""
    service, calls = preview
    doc = resume_content().model_dump()
    item = {"project_id": project["id"], "revision_id": populated["id"], "highlight_ids": ["one"]}
    with pytest.raises(Problem, match="不可用"):
        service.render("missing", doc, [])
    for invalid in (
        [item, item],
        [{**item, "project_id": "wrong"}],
        [{**item, "highlight_ids": ["missing"]}],
        [{**item, "highlight_ids": ["one", "one"]}],
    ):
        with pytest.raises(Problem):
            service.render("mapped", doc, invalid)
    assert not calls
    service.render("mapped", doc, [item])
    source = service.data_dir / "templates/mapped/template.docx"
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(Problem, match="程序外变化"):
        service.render("mapped", doc, [item])
    assert len(calls) == 1


def test_preview_routes_enforce_auth_instance_and_file_scope(tmp_path, monkeypatch):
    """预览接口要求令牌和正确来源，只能读取本实例公布的预览文件。"""
    app = create_app(Config(data_dir=tmp_path / "left", token="left"))
    other = create_app(Config(data_dir=tmp_path / "right", token="right"))
    register_template(app.state.services.catalog, tmp_path / "left")
    monkeypatch.setattr(
        "resume_maker.services.resume_previews.render_word", lambda *_: (None, "No renderer")
    )
    body = {"template_id": "mapped", "document": resume_content().model_dump(), "items": []}
    with TestClient(app) as client, TestClient(other) as right:
        assert client.post("/api/resume-previews", json=body).status_code == 401
        headers = {"x-resume-token": "left"}
        assert (
            client.post(
                "/api/resume-previews",
                json=body,
                headers={**headers, "origin": "https://untrusted.test"},
            ).status_code
            == 403
        )
        response = client.post("/api/resume-previews", json=body, headers=headers)
        assert response.status_code == 200
        base = f"/api/resume-previews/{response.json()['id']}"
        assert client.get(base + "/resume.docx").status_code == 401
        assert client.get(base + "/resume.docx", headers=headers).status_code == 200
        for filename in (
            "template.docx",
            "page-0.png",
            "page-1.png",
            "resume.pdf",
            "manifest.json",
        ):
            assert client.get(base + "/" + filename, headers=headers).status_code == 404
        assert (
            right.get(base + "/resume.docx", headers={"x-resume-token": "right"}).status_code == 404
        )
        assert app.state.services.db.all("SELECT * FROM exports") == []
