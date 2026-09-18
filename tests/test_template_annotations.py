"""区分默认注释分隔线与真实注释以免误拦截或遗漏原文"""

from zipfile import ZipFile

import pytest
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import OxmlElement
from fastapi.testclient import TestClient
from test_template_analysis import TemplateProvider, completed, simple_document

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.templates.fill import fill_template
from resume_maker.integrations.word.templates.mapping import TemplatePackage


def add_annotation_part(doc, kind, content):
    """为脱敏文档添加带内容类型和关系的标准注释部件"""
    part = Part(
        PackURI(f"/word/{kind}s.xml"),
        f"application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}s+xml",
        f'<w:{kind}s xmlns:w="{NS["w"]}">{content}</w:{kind}s>'.encode(),
        doc.part.package,
    )
    doc.part.relate_to(part, getattr(RELATIONSHIP_TYPE, kind.upper() + "S"))


def test_default_annotation_parts_allow_analysis_and_filling(tmp_path):
    """默认分隔线和空批注部件不阻止 AI 识别及填充；导出时仍原样保留部件"""
    source, output = tmp_path / "source.docx", tmp_path / "output.docx"
    doc = Document()
    doc.add_paragraph("原姓名")
    for kind in ("footnote", "endnote"):
        add_annotation_part(
            doc,
            kind,
            f'<w:{kind} w:type="separator" w:id="-1"><w:p><w:r>'
            f"<w:separator/></w:r></w:p></w:{kind}>"
            f'<w:{kind} w:type="continuationSeparator" w:id="0"><w:p><w:r>'
            f"<w:continuationSeparator/></w:r></w:p></w:{kind}>",
        )
    add_annotation_part(doc, "comment", "")
    doc.save(source)
    app = create_app(Config(data_dir=tmp_path / "data", token="test"), TemplateProvider())
    with TestClient(app) as client:
        response = client.post(
            "/api/templates/analyses",
            json={"path": str(source), "document": simple_document().model_dump()},
            headers={"x-resume-token": "test"},
        )
        assert response.status_code == 200
        task = completed(app.state.services.templates, response.json()["id"])
        assert task["status"] == "completed" and task["review"]["ready"]
        from resume_maker.domain.templates import TemplatePlan

        fill_template(
            source,
            output,
            TemplatePlan.model_validate(task["plan"]),
            simple_document().model_dump(),
            [],
        )
    assert Document(output).paragraphs[0].text == "新的用户资料"
    with ZipFile(source) as before, ZipFile(output) as after:
        for kind in ("footnote", "endnote"):
            part = f"word/{kind}s.xml"
            assert before.read(part) == after.read(part)
        assert "word/comments.xml" not in after.namelist()


@pytest.mark.parametrize("kind", ["footnote", "endnote", "comment"])
@pytest.mark.parametrize("content", ["", "<w:p><w:r><w:t>注释中的原资料</w:t></w:r></w:p>"])
def test_annotations_participate_in_recognition_without_blocking(tmp_path, kind, content):
    """脚注尾注按普通文字识别；批注自动忽略；均不阻止导入"""
    doc = Document()
    doc.add_paragraph("原姓名")
    add_annotation_part(doc, kind, f'<w:{kind} w:id="0">{content}</w:{kind}>')
    source = tmp_path / "annotations.docx"
    doc.save(source)
    inventory = TemplatePackage(source).inventory()
    assert not inventory["warnings"]
    annotation_text = [
        row["text"] for row in inventory["nodes"] if row["part"] != "word/document.xml"
    ]
    if kind == "comment":
        assert not annotation_text and inventory["notices"]
    elif content:
        assert "注释中的原资料" in annotation_text


@pytest.mark.parametrize("kind", ["footnote", "endnote"])
def test_custom_separator_text_is_included(tmp_path, kind):
    """分隔线中的用户文字也参与映射以防遗漏原资料"""
    doc = Document()
    doc.add_paragraph("原姓名")
    add_annotation_part(
        doc,
        kind,
        f'<w:{kind} w:type="separator" w:id="-1"><w:p><w:r>'
        f"<w:t>分隔线中的原资料</w:t></w:r></w:p></w:{kind}>",
    )
    source = tmp_path / "custom-separator.docx"
    doc.save(source)
    inventory = TemplatePackage(source).inventory()
    assert not inventory["warnings"]
    assert "分隔线中的原资料" in [row["text"] for row in inventory["nodes"]]


@pytest.mark.parametrize("tag", ["footnoteReference", "endnoteReference", "commentRangeStart"])
def test_annotation_references_without_parts_are_reported(tmp_path, tag):
    """缺失注释部件时仍检查正文引用且不能把未处理的注释锚点放行"""
    doc = Document()
    reference = OxmlElement(f"w:{tag}")
    reference.set(w("id"), "1")
    doc.add_paragraph("原姓名").add_run()._r.append(reference)
    source = tmp_path / "reference.docx"
    doc.save(source)
    inventory = TemplatePackage(source).inventory()
    if tag == "commentRangeStart":
        assert not inventory["warnings"] and inventory["notices"]
    else:
        assert not inventory["warnings"]
        assert "失效" in "".join(inventory["notices"])


def test_malformed_annotation_xml_reports_invalid_document(tmp_path):
    """损坏的注释 XML 转换为文档错误且不能触发未处理的解析异常"""
    doc = Document()
    doc.add_paragraph("原姓名")
    add_annotation_part(doc, "footnote", "<w:footnote>")
    source = tmp_path / "invalid.docx"
    doc.save(source)
    with pytest.raises(Problem, match="有效的 Word DOCX"):
        TemplatePackage(source)
