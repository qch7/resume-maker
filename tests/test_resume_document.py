"""完整简历资料的持久化、层级校验、完整保存与 Word 排版行为"""

from copy import deepcopy
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from lxml import etree
from pydantic import ValidationError

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.domain.models import ResumeItem
from resume_maker.domain.resume import ResumeDocument
from resume_maker.infrastructure.database import Database
from resume_maker.infrastructure.storage import create_backup, restore_backup
from resume_maker.integrations.word.full_resume import write_full_resume
from resume_maker.integrations.word.ooxml import NS
from resume_maker.services.catalog import Catalog
from resume_maker.services.documents import Documents


def document_data():
    """生成不含用户真实资料的完整简历；覆盖父栏目、子栏目与空栏目"""
    return {
        "personal": {
            "name": "测试同学",
            "phone": "10000000000",
            "gpa": "GPA 4.2 / 5",
            "email": "student@example.com",
            "age": "21",
            "gender": "男",
        },
        "sections": [
            {
                "id": "education",
                "title": "教育背景",
                "kind": "education",
                "entries": [
                    {
                        "id": "school",
                        "title": "示例大学",
                        "subtitle": "计算机科学 · 本科",
                        "period": "2024 – 2028",
                    }
                ],
            },
            {
                "id": "courses",
                "title": "主修课程",
                "parent_id": "education",
                "entries": [{"id": "courses-body", "details": "数据结构、操作系统\n计算机网络"}],
            },
            {"id": "projects", "title": "项目经历", "kind": "projects"},
            {
                "id": "skills",
                "title": "专业技能",
                "entries": [{"id": "python", "title": "后端开发", "details": "Python、FastAPI"}],
            },
            {"id": "empty", "title": "空白荣誉栏目"},
        ],
    }


def test_profile_persists_across_restart_and_backup(catalog, tmp_path):
    """完整资料可重启、备份恢复；保存时仍检查方案版本"""
    content = ResumeDocument.model_validate(document_data())
    resume = catalog.save_resume("完整简历", None, [], document=content)
    restarted = Catalog(Database(catalog.db.path))
    saved = restarted.save_resume("重命名", None, [], resume["id"], resume["version"], content)
    assert saved["document"] == content.model_dump()
    other = catalog.save_resume("另一个方案", None, [])
    assert other["document"] is None
    with pytest.raises(Problem, match="其他窗口"):
        catalog.save_resume("过时窗口", None, [], resume["id"], resume["version"], content)
    backup = create_backup(catalog.db, catalog.db.path.parent)
    restore_backup(backup, tmp_path / "restored")
    restored = Database(tmp_path / "restored" / "resume.db")
    assert (
        restored.one("SELECT * FROM resumes WHERE id=?", (resume["id"],))["document"]
        == saved["document"]
    )


def test_resume_save_replaces_document_instead_of_retaining_previous_fields(catalog):
    """完整替换方案时按请求保存资料；空资料不会隐式保留上一次内容"""
    content = ResumeDocument.model_validate(document_data())
    resume = catalog.save_resume("完整简历", None, [], document=content)
    saved = catalog.save_resume("项目组合", None, [], resume["id"], resume["version"], None)
    assert saved["document"] is None
    assert saved["version"] == resume["version"] + 1


@pytest.mark.parametrize(
    "change",
    ["orphan", "cycle", "deep", "duplicate", "no-project", "two-projects", "nested-project"],
)
def test_invalid_hierarchy_is_rejected(change):
    """错误层级不能被持久化以免预览遗漏资料或陷入递归"""
    data = document_data()
    sections = data["sections"]
    if change == "orphan":
        sections[1]["parent_id"] = "missing"
    elif change == "cycle":
        sections[0]["parent_id"] = "courses"
    elif change == "deep":
        sections[3]["parent_id"] = "courses"
    elif change == "duplicate":
        sections.append(deepcopy(sections[0]))
    elif change == "no-project":
        sections.pop(2)
    elif change == "two-projects":
        sections.append({"id": "another", "title": "重复项目", "kind": "projects"})
    elif change == "nested-project":
        sections[2]["parent_id"] = "education"
    with pytest.raises(ValidationError):
        ResumeDocument.model_validate(data)


def test_full_word_follows_sections_and_preserves_pinned_projects(
    catalog, project, populated, tmp_path, monkeypatch
):
    """真实 DOCX 包包含抬头、分层资料及选中亮点；且排序、隐藏按方案生效"""
    content = ResumeDocument.model_validate(document_data())
    # 将专业技能放在教育背景之前且不改变教育下课程的归属
    content.sections.insert(0, content.sections.pop(3))
    resume = catalog.save_resume(
        "完整简历",
        None,
        [ResumeItem(project_id=project["id"], revision_id=populated["id"], highlight_ids=["two"])],
        document=content,
    )
    monkeypatch.setattr(
        "resume_maker.services.documents.render_word", lambda *_: (None, "No renderer")
    )
    exporter = Documents(catalog, tmp_path / "data")
    result = exporter.export(resume["id"])
    path = tmp_path / "data" / "exports" / result["id"] / "resume.docx"
    with ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    text = "".join(root.xpath("//w:t/text()", namespaces=NS))
    assert text.index("测试同学") < text.index("专业技能") < text.index("教育背景")
    assert text.index("示例大学") < text.index("主修课程") < text.index("项目经历")
    assert "空白荣誉栏目" not in text
    assert "21岁" in text and "GPA 4.2 / 5" in text
    assert "Export Word" in text and "Parse documents" not in text
    assert result["manifest"]["resume"]["document"] == content.model_dump()
    assert result["manifest"]["items"][0]["revision_id"] == populated["id"]
    content.sections[1].visible = False
    saved = catalog.save_resume("完整简历", None, [], resume["id"], resume["version"], content)
    result = exporter.export(saved["id"])
    with ZipFile(tmp_path / "data" / "exports" / result["id"] / "resume.docx") as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    text = "".join(root.xpath("//w:t/text()", namespaces=NS))
    assert "教育背景" not in text and "主修课程" not in text
    assert "专业技能" in text and "项目经历" not in text


def test_profile_http_roundtrip_and_invalid_updates(tmp_path):
    """通过真实 HTTP 请求保存和更新资料；拒绝坏层级且不覆盖原始方案"""
    headers = {"x-resume-token": "test-token"}
    with TestClient(create_app(Config(data_dir=tmp_path, token="test-token"))) as client:
        response = client.post(
            "/api/resumes",
            headers=headers,
            json={"name": "资料测试", "items": [], "document": document_data()},
        )
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["document"]["personal"]["email"] == "student@example.com"
        payload = {
            "name": "已编辑",
            "items": [],
            "version": saved["version"],
            "document": saved["document"],
        }
        payload["document"]["personal"]["phone"] = "20000000000"
        payload["document"]["personal"]["hidden_fields"] = ["phone"]
        payload["document"]["personal"]["custom_fields"] = [
            {"id": "city", "label": "籍贯", "value": "杭州", "visible": True}
        ]
        payload["document"]["sections"][0]["entries"][0]["hidden_fields"] = ["period"]
        payload["document"]["sections"][0]["entries"][0]["custom_fields"] = [
            {"id": "topic", "label": "研究方向", "value": "智能系统", "visible": False}
        ]
        payload["document"]["sections"][1]["entries"][0]["visible"] = False
        response = client.put(f"/api/resumes/{saved['id']}", headers=headers, json=payload)
        assert response.status_code == 200, response.text
        payload["version"] += 1
        payload["document"]["sections"][1]["parent_id"] = "missing"
        assert (
            client.put(f"/api/resumes/{saved['id']}", headers=headers, json=payload).status_code
            == 422
        )
        state = client.get("/api/state", headers=headers).json()
        assert state["resumes"][0]["document"]["personal"]["phone"] == "20000000000"
        assert state["resumes"][0]["document"]["sections"][1]["parent_id"] == "education"
    # 重启后字段和整条显隐仍在；隐藏的资料原值保持可恢复
    with TestClient(create_app(Config(data_dir=tmp_path, token="test-token"))) as client:
        data = client.get("/api/state", headers=headers).json()["resumes"][0]["document"]
        assert data["personal"]["hidden_fields"] == ["phone"]
        assert data["personal"]["phone"] == "20000000000"
        assert data["personal"]["custom_fields"][0]["value"] == "杭州"
        assert data["sections"][0]["entries"][0]["custom_fields"][0] == {
            "id": "topic",
            "label": "研究方向",
            "value": "智能系统",
            "visible": False,
        }
        assert data["sections"][0]["entries"][0]["hidden_fields"] == ["period"]
        assert data["sections"][0]["entries"][0]["period"] == "2024 – 2028"
        assert data["sections"][1]["entries"][0]["visible"] is False


@pytest.mark.parametrize("with_projects", [False, True])
def test_project_children_persist_and_export_after_project_content(
    catalog, tmp_path, with_projects
):
    """项目区也允许两级资料；空项目仍展示子栏目；父级隐藏时一并省略"""
    data = document_data()
    data["sections"][1]["parent_id"] = "projects"
    content = ResumeDocument.model_validate(data)
    saved = catalog.save_resume("项目子栏目", None, [], document=content)
    assert saved["document"]["sections"][1]["parent_id"] == "projects"
    projects = (
        [
            {
                "content": {
                    "title": "固定项目正文",
                    "period": "2026",
                    "stack": [],
                    "role": "",
                    "description": "",
                    "highlights": [],
                },
                "highlight_ids": [],
            }
        ]
        if with_projects
        else []
    )
    path = tmp_path / "project-children.docx"
    write_full_resume(path, saved["document"], projects)
    with ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    text = "".join(root.xpath("//w:t/text()", namespaces=NS))
    assert text.index("项目经历") < text.index("主修课程") < text.index("数据结构")
    assert text.count("主修课程") == 1
    if with_projects:
        assert text.index("项目经历") < text.index("固定项目正文") < text.index("主修课程")
    data["sections"][2]["visible"] = False
    write_full_resume(path, data, projects)
    with ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    text = "".join(root.xpath("//w:t/text()", namespaces=NS))
    assert "项目经历" not in text and "主修课程" not in text and "固定项目正文" not in text


@pytest.mark.parametrize("parent_id", ["education", None])
def test_word_deduplicates_course_titles_at_both_levels(tmp_path, parent_id):
    """同名条目标题在子栏目和大栏目都不会重复；独立条目名称仍完整显示"""
    data = document_data()
    courses = data["sections"][1]
    courses["parent_id"] = parent_id
    courses["entries"][0]["title"] = " 主修课程 "
    courses["entries"].append({"id": "electives", "title": "选修课程", "details": "计算机视觉"})
    original = deepcopy(data)
    path = tmp_path / "deduplicated.docx"
    write_full_resume(path, data, [])
    with ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    text = "".join(root.xpath("//w:t/text()", namespaces=NS))
    assert text.count("主修课程") == 1
    assert "数据结构、操作系统" in text and "选修课程" in text and "计算机视觉" in text
    assert data == original


def test_word_omits_hidden_fields_rows_photos_and_empty_headings(tmp_path):
    """真实 Word 文件不含隐藏文字与照片；全部隐藏的栏目不留下空标题"""
    data = document_data()
    personal = data["personal"]
    personal.update(job_title="隐藏的岗位", location="隐藏的城市", website="hidden.example.com")
    personal["photo"] = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1sAAAAASUVORK5CYII="
    )
    personal["hidden_fields"] = list(personal)
    school = data["sections"][0]["entries"][0]
    school["hidden_fields"] = ["subtitle", "period"]
    courses = data["sections"][1]
    courses["entries"][0].update(title="主修课程", hidden_fields=["details"])
    data["sections"][3]["entries"][0]["visible"] = False
    path = tmp_path / "hidden.docx"
    write_full_resume(path, data, [])
    with ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
        assert not any(name.startswith("word/media/") for name in archive.namelist())
    text = "".join(root.xpath("//w:t/text()", namespaces=NS))
    assert "教育背景" in text and "示例大学" in text
    for field in personal["hidden_fields"]:
        assert personal[field] not in text
    for hidden in ["计算机科学", "2024", "主修课程", "操作系统", "专业技能", "后端开发"]:
        assert hidden not in text
    assert school["subtitle"] == "计算机科学 · 本科"
    assert courses["entries"][0]["details"] == "数据结构、操作系统\n计算机网络"


@pytest.mark.parametrize("target,field", [("personal", "unknown"), ("entry", "visible")])
def test_visibility_rejects_unknown_field_names(target, field):
    """显隐配置只能指向资料字段且不能借此覆盖条目标识或其他元数据"""
    data = document_data()
    item = data["personal"] if target == "personal" else data["sections"][0]["entries"][0]
    item["hidden_fields"] = [field]
    with pytest.raises(ValidationError):
        ResumeDocument.model_validate(data)


def test_word_includes_custom_information_and_omits_empty_hidden_items(tmp_path):
    """自定义信息可独立形成栏目正文；导出只使用可见完整项且保留原始资料"""
    data = document_data()
    data["personal"]["custom_fields"] = [
        {"id": "city", "label": " 籍贯 ", "value": " 杭州 ", "visible": True},
        {"id": "hidden", "label": "隐藏标签", "value": "隐藏正文", "visible": False},
        {"id": "empty-name", "label": " ", "value": "无名称正文"},
        {"id": "empty-value", "label": "无内容标签", "value": " "},
    ]
    data["sections"][1]["entries"] = [
        {
            "id": "only-custom",
            "title": "主修课程",
            "custom_fields": [
                {"id": "topic", "label": "研究方向", "value": "智能系统"},
                {
                    "id": "hidden",
                    "label": "条目隐藏标签",
                    "value": "条目隐藏正文",
                    "visible": False,
                },
            ],
        }
    ]
    original = deepcopy(data)
    path = tmp_path / "custom-info.docx"
    write_full_resume(path, data, [])
    with ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    text = "".join(root.xpath("//w:t/text()", namespaces=NS))
    assert "籍贯：杭州" in text and "研究方向：智能系统" in text
    assert text.count("主修课程") == 1
    for excluded in ["隐藏标签", "隐藏正文", "无名称正文", "无内容标签"]:
        assert excluded not in text
    assert data == original
    data["sections"][1]["entries"][0]["visible"] = False
    write_full_resume(path, data, [])
    with ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    text = "".join(root.xpath("//w:t/text()", namespaces=NS))
    assert "主修课程" not in text and "智能系统" not in text


@pytest.mark.parametrize("target", ["personal", "entry"])
def test_custom_fields_validate_identity_and_limits(target):
    """拒绝同组重复标识和超量字段以免编辑定位混乱或保存无法恢复"""
    data = document_data()
    item = data["personal"] if target == "personal" else data["sections"][0]["entries"][0]
    item["custom_fields"] = [{"id": "duplicate"}, {"id": "duplicate"}]
    with pytest.raises(ValidationError, match="标识不能重复"):
        ResumeDocument.model_validate(data)
    item["custom_fields"] = [{"id": str(index)} for index in range(21)]
    with pytest.raises(ValidationError):
        ResumeDocument.model_validate(data)
