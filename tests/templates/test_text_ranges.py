"""验证段落位置索引保留跨运行样式、控制字符及独立文本框"""

from copy import deepcopy
from random import Random

import pytest
from lxml import etree

from resume_maker.domain.templates import TextBinding
from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.templates import fill, text_ranges
from resume_maker.integrations.word.templates.mapping import paragraph_text
from resume_maker.integrations.word.templates.text_ranges import ParagraphTextIndex


def fragmented_paragraph(parts):
    """用独立字体运行、空文字及超链接构造易受替换影响的段落"""
    paragraph = etree.Element(w("p"), nsmap={"w": NS["w"]})
    for index, part in enumerate(parts):
        parent = paragraph
        if index % 3 == 0:
            parent = etree.SubElement(paragraph, w("hyperlink"))
            parent.set(w("anchor"), "原链接")
        run = etree.SubElement(parent, w("r"))
        properties = etree.SubElement(run, w("rPr"))
        etree.SubElement(properties, w("sz")).set(w("val"), str(20 + index))
        etree.SubElement(run, w("t")).text = part
        if index % 2 == 0:
            etree.SubElement(run, w(("br", "cr", "tab")[index % 3]))
    return paragraph


@pytest.mark.parametrize("seed", range(12))
def test_index_matches_descending_rebuild_for_fragmented_runs(seed):
    """不重叠替换复用索引后仍逐字节等于每次重读段落的结果"""
    random = Random(seed)
    parts = ["".join(random.choices("甲乙 丙丁", k=random.randrange(7))) for _ in range(35)]
    paragraph = fragmented_paragraph(parts)
    expected = deepcopy(paragraph)
    length = len(paragraph_text(paragraph))
    points = sorted(random.sample(range(length + 1), 16))
    replacements = [
        (start, end, random.choice(["新内容", "", "新\n的\n内容", " ", "\n"]))
        for start, end in zip(points[::2], points[1::2], strict=True)
    ]
    for replacement in sorted(replacements, reverse=True):
        ParagraphTextIndex(expected).apply([replacement])
    ParagraphTextIndex(paragraph).apply(replacements)
    assert etree.tostring(paragraph) == etree.tostring(expected)


def test_same_run_preserves_newlines_and_boundary_controls():
    """同一运行右侧新增换行不干扰左侧替换，端点控制节点保持原位"""
    paragraph = fragmented_paragraph(["甲乙丙丁戊己"])
    ParagraphTextIndex(paragraph).apply([(0, 2, "左\n侧"), (2, 4, "中"), (4, 6, "右\n侧")])
    assert paragraph_text(paragraph) == "左侧中右侧"
    assert [node.text for node in paragraph.iter(w("t"))] == ["左", "侧中右", "侧"]
    assert len(list(paragraph.iter(w("br")))) == 3
    assert not list(paragraph.iter(w("hyperlink")))
    assert paragraph.find("w:r/w:rPr/w:sz", NS).get(w("val")) == "20"


def test_index_isolates_nested_textbox_and_prefers_nonspace_style():
    """空白样式不接收正文，外段替换不触及文本框内的文字及控制节点"""
    paragraph = fragmented_paragraph([" ", "原内容", "尾部"])
    textbox = etree.SubElement(paragraph[0][0], w("txbxContent"))
    nested = etree.SubElement(textbox, w("p"))
    run = etree.SubElement(nested, w("r"))
    etree.SubElement(run, w("t")).text = "文本框"
    etree.SubElement(run, w("tab"))
    original = etree.tostring(nested)
    ParagraphTextIndex(paragraph).apply([(0, 4, "新内容")])
    assert paragraph_text(paragraph) == "新内容尾部"
    assert etree.tostring(nested) == original
    replacement = next(node for node in paragraph.iter(w("t")) if node.text == "新内容")
    assert replacement.getparent().find("w:rPr/w:sz", NS).get(w("val")) == "21"


@pytest.mark.parametrize(
    "replacements,expected",
    [([(0, 0, "补充")], "甲乙丙丁补充"), ([(0, 3, "甲"), (2, 4, "乙")], "甲")],
)
def test_empty_or_overlapping_ranges_keep_sequential_semantics(replacements, expected):
    """空映射插入及隐藏字段扩展后的重叠范围继续按当前文字倒序处理"""
    paragraph = etree.Element(w("p"))
    etree.SubElement(etree.SubElement(paragraph, w("r")), w("t")).text = "甲乙丙丁"
    ParagraphTextIndex(paragraph).apply(replacements)
    assert paragraph_text(paragraph) == expected


def test_many_fields_build_one_paragraph_index(monkeypatch):
    """一百个映射共用一次位置扫描，不按映射数反复收集全部文字节点"""
    paragraph = fragmented_paragraph(list("占位|" * 100))
    fields = [
        TextBinding(node="p", quote="占位", occurrence=index + 1, target="highlights")
        for index in range(100)
    ]
    scans = []
    original = ParagraphTextIndex.__init__

    def counted(self, node):
        """记录完整段落索引的构造次数"""
        scans.append(node)
        original(self, node)

    monkeypatch.setattr(text_ranges.ParagraphTextIndex, "__init__", counted)
    values = {"_highlight_items": [f"亮点{index}" for index in range(100)]}
    fill.fill_fields({"p": paragraph}, fields, values)
    assert scans == [paragraph]
    assert paragraph_text(paragraph) == "".join(f"亮点{index}|" for index in range(100))


def test_hidden_age_overlapping_unit_keeps_descending_replacement():
    """隐藏年龄时扩展的单位范围沿用原倒序语义，仍可覆盖右侧已替换的内容"""
    paragraph = etree.Element(w("p"))
    etree.SubElement(etree.SubElement(paragraph, w("r")), w("t")).text = "年龄：18 岁"
    bindings = [
        TextBinding(node="p", quote="18", target="personal.age"),
        TextBinding(node="p", quote="岁", target="personal.custom:单位"),
    ]
    fill.fill_fields({"p": paragraph}, bindings, {"personal.custom:单位": "周"})
    assert paragraph_text(paragraph) == "年龄："


@pytest.mark.parametrize("control", [None, "br", "cr", "tab"])
def test_adjacent_metadata_retains_original_control_boundary(control):
    """紧贴字段只在原文缺少控制分隔时补间距"""
    paragraph = etree.Element(w("p"))
    run = etree.SubElement(paragraph, w("r"))
    etree.SubElement(run, w("t")).text = "旧标题"
    if control:
        etree.SubElement(run, w(control))
    etree.SubElement(run, w("t")).text = "旧日期"
    fields = [
        TextBinding(node="p", quote="旧标题", target="title"),
        TextBinding(node="p", quote="旧日期", target="period"),
    ]
    fill.fill_fields({"p": paragraph}, fields, {"title": "新标题", "period": "新日期"})
    assert paragraph_text(paragraph) == "新标题" + ("" if control else "\u2002") + "新日期"
    if control:
        assert len(list(paragraph.iter(w(control)))) == 1
