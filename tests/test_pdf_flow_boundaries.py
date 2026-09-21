"""用独立生成的 PDF 检查记录边界、侧栏连续性以及表格误判保护"""

from io import BytesIO
from threading import Event

import pymupdf
import pytest
from docx import Document
from docx.oxml.ns import qn
from PIL import Image
from test_pdf_recovery import forbidden_fallback, quiet

from resume_maker.domain.templates import TemplatePlan
from resume_maker.integrations.word.pdf.columns import parse_sidebar
from resume_maker.integrations.word.pdf.flow import text_counter
from resume_maker.integrations.word.pdf.recovery import rebuild_pdf
from resume_maker.integrations.word.templates.fill import fill_template
from resume_maker.integrations.word.templates.mapping import TemplatePackage
from resume_maker.services.templates.analysis import complete_labels


def sidebar_pdf(path, *, offset=0, swap=False, ruled=False, secondary=True):
    """不使用用户模板或字段内容，通过错开的内部标题证明两侧是独立文字流"""
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=620, height=800)
        page.insert_text((30, 40), "Applicant", fontsize=16)
        left, right = (290 + offset, 30) if swap else (30, 290 + offset)
        for x, title in ((left, "SIDE A"), (right, "SIDE B")):
            page.insert_text((x, 110), title, fontsize=13, fontname="hebo")
        for y, text in (
            (133, "Old Alpha"),
            (154, "Old Beta"),
            (198, "Old School"),
            (219, "Old Degree"),
            (240, "2018-2022"),
        ):
            page.insert_text((left, y), text, fontsize=10)
        page.insert_text(
            (left, 177),
            "MORE A" if secondary else "Plain A",
            fontsize=13 if secondary else 10,
            fontname="hebo" if secondary else "helv",
        )
        for index, y in enumerate((133, 177)):
            page.insert_text((right, y), f"Old Project {index}", fontsize=10)
            page.insert_text((right + 160, y), f"202{index}", fontsize=10)
            page.insert_text((right, y + 21), f"Old Description {index}", fontsize=10)
        if ruled:
            for y in (115, 159, 203):
                page.draw_line((25, y), (585, y), width=0.8)
        page.insert_text((30, 290), "Full width footer " * 5, fontsize=11)
        pdf.save(path)


@pytest.mark.parametrize("offset,swap", [(0, False), (45, False), (-30, True)])
def test_sidebar_records_stay_in_one_container_and_can_repeat(tmp_path, offset, swap):
    """改变栏宽和左右位置后仍可增加项目，长尾学历和通栏页尾不能被拆入其他容器"""
    pdf, source, output = (tmp_path / name for name in ("source.pdf", "source.docx", "filled.docx"))
    sidebar_pdf(pdf, offset=offset, swap=swap)
    rebuild_pdf(pdf, source, Event(), quiet, forbidden_fallback)
    package = TemplatePackage(source)
    rows = [r for r in package.inventory()["nodes"] if r["kind"] == "p" and r["text"].strip()]
    nodes = {
        key: next(r for r in rows if key in r["text"])
        for key in (
            "SIDE A",
            "Old School",
            "Old Degree",
            "2018-2022",
            "SIDE B",
            "Old Project 0",
            "Old Project 1",
            "Old Description 0",
            "Old Description 1",
        )
    }
    assert (
        len({nodes[key]["parent"] for key in ("SIDE A", "Old School", "Old Degree", "2018-2022")})
        == 1
    )
    assert (
        len(
            {
                nodes[key]["parent"]
                for key in (
                    "SIDE B",
                    "Old Project 0",
                    "Old Project 1",
                    "Old Description 0",
                    "Old Description 1",
                )
            }
        )
        == 1
    )
    assert nodes["SIDE A"]["parent"] != nodes["SIDE B"]["parent"]
    with pymupdf.open(pdf) as pages:
        assert text_counter(pages[0].get_text()) == text_counter("".join(r["text"] for r in rows))
    repeat = {
        "section": "Entries",
        "start": nodes["Old Project 0"]["id"],
        "end": nodes["Old Description 1"]["id"],
        "sample_start": nodes["Old Project 0"]["id"],
        "sample_end": nodes["Old Description 0"]["id"],
        "fields": [
            {"node": nodes["Old Project 0"]["id"], "quote": "Old Project 0", "target": "title"},
            {"node": nodes["Old Project 0"]["id"], "quote": "2020", "target": "period"},
            {
                "node": nodes["Old Description 0"]["id"],
                "quote": "Old Description 0",
                "target": "details",
            },
        ],
    }
    plan = TemplatePlan(
        summary="独立容器",
        fields=[],
        repeats=[repeat],
        photos=[],
        keep=[r["id"] for r in rows],
        remove=[],
        warnings=[],
    )
    content = {
        "personal": {},
        "sections": [
            {"id": "projects", "title": "Projects", "kind": "projects", "visible": False},
            {
                "id": "entries",
                "title": "Entries",
                "entries": [
                    {
                        "id": str(i),
                        "title": f"New Entry {i}",
                        "period": f"203{i}",
                        "details": f"Unique body {i}",
                    }
                    for i in range(4)
                ],
            },
        ],
    }
    fill_template(source, output, plan, content, [])
    texts = "".join(t.text or "" for t in Document(output)._element.iter(qn("w:t")))
    assert "Old Project" not in texts and "Old Description" not in texts
    assert texts.count("Old School") == 1 and texts.count("Full width footer") == 5
    for i in range(4):
        assert texts.count(f"New Entry {i}") == 1 and texts.count(f"Unique body {i}") == 1


@pytest.mark.parametrize("ruled,secondary", [(True, True), (False, False)])
def test_table_headers_are_not_enough_to_transpose_rows(tmp_path, ruled, secondary):
    """横向表格线或只有一排表头时保持原解析路线，不能因列对齐就改成独立侧栏"""
    from pdf2docx import Converter

    pdf = tmp_path / "table.pdf"
    sidebar_pdf(pdf, ruled=ruled, secondary=secondary)
    converter = Converter(str(pdf))
    try:
        settings = converter.default_settings
        converter.load_pages().parse_document(**settings)
        with pymupdf.open(pdf) as pages:
            for section in converter.pages[0].sections:
                for column in section:
                    before = column.store()
                    assert not parse_sidebar(column, pages[0], settings)
                    assert column.store() == before
    finally:
        converter.close()


def test_compact_equal_style_records_do_not_merge_into_one_paragraph(tmp_path):
    """紧密排列且同字体的记录保留物理行，模型可选完整样本并删除全部旧条目"""
    pdf, source = tmp_path / "lines.pdf", tmp_path / "lines.docx"
    with pymupdf.open() as document:
        page = document.new_page()
        for index, value in enumerate(("Record A", "Body A", "Record B", "Body B")):
            page.insert_text((35, 70 + index * 16), value, fontsize=10)
        document.save(pdf)
    rebuild_pdf(pdf, source, Event(), quiet, forbidden_fallback)
    rows = [
        row["text"].strip()
        for row in TemplatePackage(source).inventory()["nodes"]
        if row["kind"] == "p" and row["text"].strip()
    ]
    assert rows == ["Record A", "Body A", "Record B", "Body B"]


def test_photo_is_independent_of_nearby_old_summary(tmp_path):
    """删除照片附近的旧学历摘要不会和照片替换冲突，不靠模型虚构空自定义字段"""
    pdf, source = tmp_path / "photo.pdf", tmp_path / "photo.docx"
    raw = BytesIO()
    Image.new("RGB", (50, 70), "navy").save(raw, format="PNG")
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((40, 60), "Applicant", fontsize=18)
        page.insert_text((40, 100), "Obsolete school summary", fontsize=11)
        page.insert_image((350, 75, 400, 145), stream=raw.getvalue())
        document.save(pdf)
    rebuild_pdf(pdf, source, Event(), quiet, forbidden_fallback)
    package = TemplatePackage(source)
    rows = package.inventory()["nodes"]
    photo = next(row for row in rows if row["kind"] == "image")
    old = next(row for row in rows if row["text"].strip() == "Obsolete school summary")
    assert old["id"] not in photo["ancestors"]
    name = next(row for row in rows if row["text"].strip() == "Applicant")
    plan = TemplatePlan(
        summary="独立照片",
        fields=[{"node": name["id"], "quote": "Applicant", "target": "personal.name"}],
        repeats=[],
        photos=[photo["id"]],
        keep=[],
        remove=[old["id"]],
        warnings=[],
    )
    assert package.review(complete_labels(package, plan))["ready"]
