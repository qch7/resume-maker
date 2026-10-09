"""当前模板预览的草稿隔离、缓存、重试和文件访问边界"""

from copy import deepcopy
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.domain.models import ResumeItem
from resume_maker.domain.resume import ResumeSection, SectionEntry
from resume_maker.infrastructure.assets import Assets
from resume_maker.plugin_packages.sys_resume.services.resumes import Resumes
from tests.support import document_services as resume_previews
from tests.support.document_services import Documents, ResumePreviews
from tests.support.documents import resume_content
from tests.support.templates import register_template


@pytest.fixture
def preview(catalog, tmp_path, monkeypatch):
    """模拟排版软件的文件输出，仍使用真实 DOCX 填充器"""
    calls = []

    def render(source, output):
        """记录排版次数并建立可下载文件以免单元测试启动 Word"""
        calls.append(source)
        output.write_bytes(b"pdf")
        (output.parent / "page-1.png").write_bytes(b"png")
        (output.parent / "page-1.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        return 1, None

    monkeypatch.setattr("tests.support.document_services.render_word", render)
    register_template(catalog, tmp_path / "data")
    service = ResumePreviews(
        Resumes(catalog, storage=catalog.db, assets=catalog.assets),
        tmp_path / "data",
    )
    yield service, calls
    service.stop()


def test_current_template_uses_unsaved_content_without_publishing(
    preview, catalog, project, populated, tmp_path
):
    """未保存的个人资料和经历进入模板，正式版本、草稿、方案和导出记录均不被改写"""
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
        ZipFile(BytesIO(catalog.assets.read_file("templates/mapped", "template.docx"))) as source,
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
    assert service.file(result["id"], "page-1.svg").is_file()
    for filename in (
        "template.docx",
        "page-0.png",
        "page-2.png",
        "page-0.svg",
        "page-2.svg",
        "../template.docx",
    ):
        with pytest.raises(Problem, match="不存在"):
            service.file(result["id"], filename)
    assert service.render("mapped", document, items) == result
    assert len(calls) == 1
    document["personal"]["name"] = "继续输入的姓名"
    assert service.render("mapped", document, items)["id"] != result["id"]
    items[0]["highlight_ids"] = ["two"]
    assert service.render("mapped", document, items)["id"] != result["id"]
    assert len(calls) == 3


@pytest.mark.parametrize("template_id", ["mapped", None])
def test_complete_template_preview_matches_formal_export(
    preview, catalog, project, populated, tmp_path, monkeypatch, template_id
):
    """完整模板的预览和正式导出具有相同内容和版式，关闭只回收临时预览"""
    service, _ = preview
    documents = Documents(
        Resumes(catalog, storage=catalog.db, assets=catalog.assets),
        tmp_path / "data",
        storage=catalog.db,
        assets=Assets(catalog.db, tmp_path / "data"),
    )
    document = resume_content()
    # 预览和正式导出均须自动补齐模板缺少的字段
    document.personal.website = "https://example.test/new-profile"
    document.personal.age = "23"
    document.personal.hidden_fields = ["phone"]
    document.sections.reverse()
    document.sections.insert(
        0,
        ResumeSection(
            id="internship",
            title="实习经历",
            entries=[SectionEntry(id="company", title="示例公司", details="研发实习内容")],
        ),
    )
    source = catalog.assets.read_file("templates/mapped", "template.docx")
    original = source
    mapping = deepcopy(
        Resumes(catalog, storage=catalog.db, assets=catalog.assets).template("mapped")["mapping"]
    )
    catalog.put_draft(
        project["id"],
        populated["id"],
        "meta",
        {
            "role": "仅保留的角色原文",
            "hidden_fields": ["role", "stack"],
            "custom_fields": [
                {"id": "link", "label": "项目链接", "value": "https://example.test/project"}
            ],
        },
        0,
    )
    saved = catalog.save_revision(project["id"], populated["id"], populated["id"])
    item = ResumeItem(project_id=project["id"], revision_id=saved["id"], highlight_ids=["two"])
    result = service.render(template_id, document.model_dump(), [item.model_dump()])
    resume = Resumes(catalog, storage=catalog.db, assets=catalog.assets).save_resume(
        "固定方案", template_id, [item], document=document
    )
    monkeypatch.setattr(
        "tests.support.document_services.render_word", lambda *_: (None, "No renderer")
    )
    exported = documents.export(resume["id"])
    with (
        ZipFile(service.file(result["id"], "resume.docx")) as left,
        ZipFile(
            BytesIO(catalog.assets.read_file(f"exports/{exported['id']}", "resume.docx"))
        ) as right,
    ):
        assert left.namelist() == right.namelist()
        assert all(left.read(name) == right.read(name) for name in left.namelist())
        xml = left.read("word/document.xml").decode()
        assert "https://example.test/new-profile" in xml and "23" in xml
        assert "电话：" not in xml and document.personal.phone not in xml
        assert "实习经历" in xml and "示例公司" in xml and "研发实习内容" in xml
        assert "https://example.test/project" in xml
        assert "仅保留的角色原文" not in xml and "Python" not in xml
    assert exported["manifest"]["items"][0]["content"]["role"] == "仅保留的角色原文"
    assert catalog.assets.read_file("templates/mapped", "template.docx") == original
    assert (
        Resumes(catalog, storage=catalog.db, assets=catalog.assets).template("mapped")["mapping"]
        == mapping
    )
    workspace = Path(service.directory.name)
    service.stop()
    assert not workspace.exists()
    assert catalog.assets.read_file("templates/mapped", "template.docx") == original
    assert catalog.assets.read_file(f"exports/{exported['id']}", "resume.docx")


def test_failed_render_can_download_word_and_retry(preview, monkeypatch):
    """Word 不可用时仍提供试填文件，但失败不能缓存成永久结果"""
    service, _ = preview
    renderer = resume_previews.render_word
    monkeypatch.setattr(
        "tests.support.document_services.render_word", lambda *_: (None, "Word unavailable")
    )
    result = service.render("mapped", resume_content().model_dump(), [])
    assert service.file(result["id"], "resume.docx").is_file()
    with pytest.raises(Problem, match="不存在"):
        service.file(result["id"], "resume.pdf")
    monkeypatch.setattr("tests.support.document_services.render_word", renderer)
    retry = service.render("mapped", resume_content().model_dump(), [], force=True)
    assert retry["id"] != result["id"]
    assert retry["pages"] == 1


def test_rejects_invalid_references_and_changed_template(preview, project, populated):
    """缓存不能绕过模板哈希、项目归属和选中亮点的核验"""
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
    asset_id = service.catalog.assets.file_id("templates/mapped", "template.docx")
    source = service.data_dir / "assets" / asset_id / "payload"
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(Problem, match="摘要不匹配"):
        service.render("mapped", doc, [item])
    assert len(calls) == 1


def test_preview_routes_enforce_auth_instance_and_file_scope(tmp_path, monkeypatch):
    """预览接口要求令牌和正确来源且只能读取本实例公布的预览文件"""
    monkeypatch.setattr(
        "resume_maker.plugin_packages.ext_word.integrations.word.controlled.ControlledWord.render",
        lambda *_: (None, "No renderer"),
    )
    app = create_app(Config(data_dir=tmp_path / "left", token="left"))
    other = create_app(Config(data_dir=tmp_path / "right", token="right"))
    register_template(app.state.services.catalog, tmp_path / "left")
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
        builtin = client.post(
            "/api/resume-previews", json={**body, "template_id": None}, headers=headers
        )
        assert builtin.status_code == 200
        assert builtin.json()["id"] != response.json()["id"]
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


def test_resume_results_and_cache_are_bounded(preview):
    """连续不同输入超过上限后索引和目录均回收，旧输入能重新生成"""
    service, calls = preview
    first = None
    for index in range(30):
        document = resume_content().model_dump()
        document["personal"]["name"] = f"测试用户{index}"
        result = service.render(None, document, [])
        first = first or result
    assert len(service.results) == len(service.cache) == 24
    with pytest.raises(Problem, match="失效"):
        service.file(first["id"], "resume.docx")
    assert len(calls) == 30
