"""荣誉资料复制后的保存及两种简历生成路径保持相同的字段显隐。"""

import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

from resume_maker.domain.resume import ResumeDocument
from resume_maker.integrations.word.full_resume import write_full_resume
from resume_maker.integrations.word.ooxml import NS
from resume_maker.integrations.word.template_values import section_records


def test_honor_snapshot_roundtrip_and_rendering(catalog, tmp_path):
    """前端生成的完整字段副本保存无损，内置和模板填充默认仅使用名称及日期。"""
    fixture = Path(__file__).parent / "fixtures" / "honor-entry.json"
    entry = json.loads(fixture.read_text(encoding="utf-8"))
    document = ResumeDocument.model_validate(
        {
            "sections": [
                {"id": "projects", "title": "项目经历", "kind": "projects"},
                {"id": "honors", "title": "资格与成果", "entries": [entry]},
            ]
        }
    )
    saved = catalog.save_resume("荣誉测试", None, [], document=document)
    restored = ResumeDocument.model_validate(saved["document"])
    stored = restored.sections[1].entries[0]
    assert stored.field_definitions is None
    assert stored.model_dump(exclude={"field_definitions"}) == entry
    records = section_records(restored, "资格与成果", [])
    assert len(records) == 1
    assert records[0]["title"] == entry["title"]
    assert records[0]["period"] == entry["period"]
    assert not any(records[0][key] for key in ("subtitle", "details", "custom_fields"))

    output = tmp_path / "honors.docx"
    write_full_resume(output, restored.model_dump(), [])
    text = word_text(output)
    assert entry["title"] in text and entry["period"] in text
    assert entry["subtitle"] not in text and "示例获奖项目" not in text
    for field in entry["custom_fields"]:
        assert field["value"] not in text

    stored.hidden_fields.remove("subtitle")
    stored.custom_fields[0].visible = True
    write_full_resume(output, restored.model_dump(), [])
    text = word_text(output)
    assert entry["subtitle"] in text
    assert "奖项：一等奖" in text
    assert "示例获奖项目" not in text
    records = section_records(restored, "资格与成果", [])
    assert records[0]["subtitle"] == entry["subtitle"]
    assert records[0]["custom_fields"] == "奖项：一等奖"
    assert records[0]["details"] == ""
    assert saved["document"]["sections"][1]["entries"][0] == {
        **entry,
        "field_definitions": None,
    }


def word_text(path):
    """读取真实生成 DOCX 的可见文本以检查排版采用的资料。"""
    with ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    return "".join(root.xpath("//w:t/text()", namespaces=NS))
