"""通用压页覆盖隐藏格式、分页约束及图形保护，不依赖资料名称或来源"""

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.shared import Pt
from lxml import etree

from resume_maker.domain.page_layout import LAYOUT_KEY, AutoFit
from resume_maker.integrations.word.item_layout import scaled_size
from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.page_layout import apply_page_layout
from resume_maker.integrations.word.templates.mapping import TemplatePackage

WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def drawing_paragraph(doc, *, floating=False, offset=0, bottom=0):
    """构造只含独立绘图的段落，图形尺寸及效果占位可分别核对"""
    paragraph = doc.add_paragraph()
    drawing = OxmlElement("w:drawing")
    graphic = etree.SubElement(drawing, f"{{{WP}}}{'anchor' if floating else 'inline'}")
    if floating:
        graphic.set("behindDoc", "0")
        position = etree.SubElement(graphic, f"{{{WP}}}positionV", relativeFrom="page")
        etree.SubElement(position, f"{{{WP}}}posOffset").text = str(offset)
    etree.SubElement(graphic, f"{{{WP}}}extent", cx="6000000", cy="400000")
    etree.SubElement(graphic, f"{{{WP}}}effectExtent", l="0", t="0", r="0", b=str(bottom))
    paragraph.add_run()._r.append(drawing)
    return paragraph, graphic


def compact(doc, tmp_path, **options):
    """从真实 DOCX 原件执行正式后处理，返回保留全部部件的解析结果"""
    path = tmp_path / "compact.docx"
    doc.save(path)
    apply_page_layout(path, {LAYOUT_KEY: {"options": {"auto_fit": options}}})
    return TemplatePackage(path)


def sz(parent, path="w:rPr/w:sz"):
    """按 Word 半磅存储读取明确字号"""
    return float(parent.find(path, NS).get(w("val"))) / 2


def test_text_markers_empty_runs_and_empty_paragraphs_share_actual_font_limits(tmp_path):
    """段标记及纯控制运行不能继续按十一磅撑高已经缩小的正文"""
    doc = Document()
    paragraph = doc.add_paragraph()
    paragraph.add_run("完整正文").font.size = Pt(10.5)
    paragraph.add_run().add_tab()
    paragraph.add_run().add_break()
    doc.add_paragraph()
    package = compact(doc, tmp_path, spacing_factor=0, font_scale=0.7)
    paragraphs = package.parts["word/document.xml"].findall("w:body/w:p", NS)
    assert [sz(run) for run in paragraphs[0].findall(w("r"))] == [7, 7, 7]
    assert sz(paragraphs[0], "w:pPr/w:rPr/w:sz") == 7
    assert sz(paragraphs[1], "w:pPr/w:rPr/w:sz") == 1
    assert len(paragraphs[0].findall(".//w:tab", NS)) == 1
    assert len(paragraphs[0].findall(".//w:br", NS)) == 1


def test_paragraph_mark_size_does_not_replace_inherited_visible_text_size(tmp_path):
    """段落标记只控制结束标记，不能误当正文继承字号并放大实际文字"""
    doc = Document()
    doc.styles["Normal"].font.size = Pt(10)
    paragraph = doc.add_paragraph("继承十磅正文")
    marker = OxmlElement("w:rPr")
    size = OxmlElement("w:sz")
    size.set(w("val"), "60")
    marker.append(size)
    paragraph._p.get_or_add_pPr().append(marker)
    package = compact(doc, tmp_path, font_scale=0.8)
    paragraph = package.parts["word/document.xml"].find("w:body/w:p", NS)
    assert sz(paragraph.find(w("r"))) == 8
    assert sz(paragraph, "w:pPr/w:rPr/w:sz") == 8


@pytest.mark.parametrize(
    "size,delta,scale,expected",
    [
        (20, 0, 0.75, 15),
        (10.5, 0, 0.75, 7.5),
        (10, 3, 1, 9),
        (10, 3, 0.8, 7),
        (5, 0, 0, 5),
        (72, 0, 0, 6),
        (6, 0, 0.1, 6),
    ],
)
def test_font_scaling_preserves_legacy_size_hierarchy_and_half_point_floor(
    size, delta, scale, expected
):
    """旧减字号继续按九磅解释，新比例统一向下半磅且不放大已有小字"""
    assert scaled_size(size, AutoFit(font_delta=delta, font_scale=scale)) == expected


def test_inherited_paragraph_spacing_and_fixed_lines_shrink_without_clipping(tmp_path):
    """样式继承的前后间距及固定行框均进入压缩，固定行框仍容纳最大文字"""
    doc = Document()
    parent = doc.styles.add_style("CustomParent", WD_STYLE_TYPE.PARAGRAPH)
    parent.font.size = Pt(10)
    parent.paragraph_format.space_before = Pt(8)
    parent.paragraph_format.space_after = Pt(6)
    parent.paragraph_format.line_spacing = Pt(28)
    style = doc.styles.add_style("CustomChild", WD_STYLE_TYPE.PARAGRAPH)
    style.base_style = parent
    doc.add_paragraph("固定行框中的完整文字", style=style)
    package = compact(doc, tmp_path, spacing_factor=0, font_scale=0.8)
    paragraph = package.parts["word/document.xml"].find("w:body/w:p", NS)
    spacing = paragraph.find("w:pPr/w:spacing", NS)
    assert spacing.get(w("before")) == spacing.get(w("after")) == "0"
    assert spacing.get(w("line")) == "192"
    assert spacing.get(w("lineRule")) == "exact"
    assert sz(paragraph.find(w("r"))) == 8


def test_plain_text_hard_pages_and_long_keep_chain_can_flow(tmp_path):
    """普通文字硬分页改成换行，长链只保留短首段跟随首段正文"""
    doc = Document()
    style = doc.styles.add_style("AlwaysNext", WD_STYLE_TYPE.PARAGRAPH)
    style.paragraph_format.keep_with_next = True
    style.paragraph_format.page_break_before = True
    style.paragraph_format.keep_together = True
    for index in range(6):
        paragraph = doc.add_paragraph(f"完整条目 {index}", style=style)
        if index == 3:
            paragraph.add_run().add_break(WD_BREAK.PAGE)
    doc.add_paragraph("尾部完整文字")
    package = compact(doc, tmp_path, spacing_factor=0, relax_pagination=True)
    root = package.parts["word/document.xml"]
    paragraphs = root.findall("w:body/w:p", NS)
    assert paragraphs[0].find("w:pPr/w:keepNext", NS) is None
    assert all(p.find("w:pPr/w:keepNext", NS).get(w("val")) == "0" for p in paragraphs[1:6])
    assert all(p.find("w:pPr/w:pageBreakBefore", NS).get(w("val")) == "0" for p in paragraphs[:6])
    assert all(p.find("w:pPr/w:keepLines", NS).get(w("val")) == "0" for p in paragraphs[:6])
    assert not root.findall(".//w:br[@w:type='page']", NS)
    assert len(root.findall(".//w:br", NS)) == 1
    assert "尾部完整文字" in "".join(root.itertext())


def test_fixed_text_table_rows_release_height_without_removing_cells(tmp_path):
    """纯文字表格解除固定高及不许跨页，表格内容和编辑结构完整保留"""
    doc = Document()
    table = doc.add_table(rows=4, cols=2)
    for index, row in enumerate(table.rows):
        row.height = Pt(90)
        row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        for column, cell in enumerate(row.cells):
            cell.text = f"完整单元格 {index}-{column}"
    package = compact(doc, tmp_path, spacing_factor=0, relax_pagination=True)
    root = package.parts["word/document.xml"]
    assert len(list(root.iter(w("tr")))) == 4 and len(list(root.iter(w("tc")))) == 8
    assert not list(root.iter(w("trHeight")))
    assert all(node.get(w("val")) == "0" for node in root.iter(w("cantSplit")))
    assert all(
        f"完整单元格 {i}-{j}" in "".join(root.itertext()) for i in range(4) for j in range(2)
    )


def test_positioned_objects_preserve_neighbor_spacing_pages_sections_and_extent(tmp_path):
    """页定位对象可依赖后段留白，保守保留整篇定位约束以免合页后叠图"""
    doc = Document()
    drawing = OxmlElement("w:drawing")
    anchor = etree.SubElement(
        drawing, "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}anchor"
    )
    etree.SubElement(
        anchor,
        "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent",
        cx="1200000",
        cy="700000",
    )
    doc.add_paragraph().add_run()._r.append(drawing)
    paragraph = doc.add_paragraph("图形后的完整正文")
    paragraph.paragraph_format.space_before = Pt(70)
    paragraph.paragraph_format.page_break_before = True
    paragraph.add_run().add_break(WD_BREAK.PAGE)
    original = etree.tostring(drawing)
    package = compact(doc, tmp_path, spacing_factor=0, font_scale=0.7, relax_pagination=True)
    root = package.parts["word/document.xml"]
    paragraph = root.findall("w:body/w:p", NS)[1]
    assert paragraph.find("w:pPr/w:spacing", NS).get(w("before")) == "1400"
    assert paragraph.find("w:pPr/w:pageBreakBefore", NS).get(w("val"), "1") == "1"
    assert len(root.findall(".//w:br[@w:type='page']", NS)) == 1
    assert etree.tostring(root.find(".//w:drawing", NS)) == original


def test_image_row_keeps_original_fixed_height_and_dimensions(tmp_path):
    """有图片的行不缩到图片之外，行高及绘图尺寸保持原值"""
    doc = Document()
    row = doc.add_table(rows=1, cols=1).rows[0]
    row.height = Pt(90)
    row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
    drawing = OxmlElement("w:drawing")
    inline = etree.SubElement(
        drawing, "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}inline"
    )
    etree.SubElement(
        inline,
        "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent",
        cx="500000",
        cy="800000",
    )
    row.cells[0].paragraphs[0].add_run()._r.append(drawing)
    package = compact(doc, tmp_path, spacing_factor=0, relax_pagination=True)
    root = package.parts["word/document.xml"]
    height = next(root.iter(w("trHeight")))
    assert height.get(w("val")) == "1800" and height.get(w("hRule")) == "exact"
    assert root.xpath(".//*[local-name()='extent']/@cy") == ["800000"]


def test_same_geometry_sections_can_flow_but_different_page_size_stays_separate(tmp_path):
    """只有页面配置一致的相邻节可以连续，纸张或方向变化保持分页"""
    doc = Document()
    doc.add_paragraph("第一节完整文字")
    doc.add_section()
    doc.add_paragraph("第二节完整文字")
    doc.add_section().page_width = Pt(800)
    doc.add_paragraph("第三节完整文字")
    package = compact(doc, tmp_path, relax_pagination=True)
    sections = list(package.parts["word/document.xml"].iter(w("sectPr")))
    assert sections[1].find(w("type")).get(w("val")) == "continuous"
    assert (
        sections[2].find(w("type")) is None
        or sections[2].find(w("type")).get(w("val")) != "continuous"
    )


@pytest.mark.parametrize("scale,expected", [(1, 6), (0.5, 3)])
def test_standalone_inline_drawing_reserves_scaled_following_text_clearance(
    tmp_path, scale, expected
):
    """图形下缘按紧邻文字的实际字号占位，保留原尺寸及已经更大的阴影范围"""
    doc = Document()
    drawing_paragraph(doc)
    doc.add_paragraph("紧邻图形的完整正文").runs[0].font.size = Pt(12)
    drawing_paragraph(doc, bottom=250000)
    doc.add_paragraph("已有阴影下的完整正文").runs[0].font.size = Pt(12)
    package = compact(doc, tmp_path, spacing_factor=0, font_scale=scale)
    root = package.parts["word/document.xml"]
    graphics = root.findall(f".//{{{WP}}}inline")
    assert graphics[0].find(f"{{{WP}}}effectExtent").get("b") == str(expected * 12700)
    assert graphics[1].find(f"{{{WP}}}effectExtent").get("b") == "250000"
    assert all(graphic.find(f"{{{WP}}}extent").get("cy") == "400000" for graphic in graphics)
    assert "紧邻图形的完整正文" in "".join(root.itertext())


def test_inline_clearance_resolves_inherited_font_and_does_not_accumulate(tmp_path):
    """手工间距也保留图形边界，继承字号参与计算且重复后处理不累计留白"""
    doc = Document()
    paragraph, graphic = drawing_paragraph(doc)
    graphic.remove(graphic.find(f"{{{WP}}}effectExtent"))
    style = doc.styles.add_style("FollowingBody", WD_STYLE_TYPE.PARAGRAPH)
    style.font.size = Pt(14)
    doc.add_paragraph("继承字号的正文", style=style)
    path = tmp_path / "manual.docx"
    doc.save(path)
    options = {LAYOUT_KEY: {"options": {"space_after": 0}}}
    for _ in range(2):
        apply_page_layout(path, options)
        root = TemplatePackage(path).parts["word/document.xml"]
        inline = root.find(f".//{{{WP}}}inline")
        assert inline.find(f"{{{WP}}}effectExtent").get("b") == str(7 * 12700)
        assert inline.find(f"{{{WP}}}extent").get("cy") == "400000"


def test_inline_images_in_text_and_images_without_following_text_keep_effect_bounds(tmp_path):
    """正文内的图标、已有完整空段让位的绘图及尾图不增加独立绘图留白"""
    doc = Document()
    paragraph, _ = drawing_paragraph(doc)
    paragraph.add_run("段内图标")
    doc.add_paragraph("下一段正文")
    drawing_paragraph(doc)
    doc.add_paragraph()
    doc.add_paragraph("已有空段让位")
    drawing_paragraph(doc)
    package = compact(doc, tmp_path)
    root = package.parts["word/document.xml"]
    assert root.xpath(".//*[local-name()='effectExtent']/@b") == ["0", "0", "0"]


def test_top_positioned_graphic_protects_prefix_but_releases_following_flow(tmp_path):
    """页顶图形及前后让位段落保留原值，后续长链、空段、正文标记可通用压缩"""
    doc = Document()
    doc.add_paragraph("页首已有文字").runs[0].font.size = Pt(14)
    anchor_paragraph, graphic = drawing_paragraph(doc, floating=True)
    anchor_paragraph.add_run("图形锚点上的文字")
    doc.add_paragraph().paragraph_format.space_after = Pt(30)
    style = doc.styles.add_style("BodyChain", WD_STYLE_TYPE.PARAGRAPH)
    style.paragraph_format.keep_with_next = True
    style.paragraph_format.page_break_before = True
    style.paragraph_format.space_before = Pt(8)
    style.font.size = Pt(12)
    for index in range(4):
        doc.add_paragraph(f"完整正文 {index}", style=style)
    doc.add_paragraph()
    original = etree.tostring(graphic)
    package = compact(doc, tmp_path, spacing_factor=0, font_scale=0.5, relax_pagination=True)
    root = package.parts["word/document.xml"]
    paragraphs = root.findall("w:body/w:p", NS)
    assert sz(paragraphs[0], "w:pPr/w:rPr/w:sz") >= 11
    assert paragraphs[2].find("w:pPr/w:spacing", NS).get(w("after")) == "600"
    assert sz(paragraphs[2], "w:pPr/w:rPr/w:sz") >= 11
    assert sz(paragraphs[-1], "w:pPr/w:rPr/w:sz") == 1
    for paragraph in paragraphs[3:7]:
        assert sz(paragraph, "w:pPr/w:rPr/w:sz") == 6
        assert paragraph.find("w:pPr/w:spacing", NS).get(w("before")) == "0"
        assert paragraph.find("w:pPr/w:pageBreakBefore", NS).get(w("val")) == "0"
    assert etree.tostring(root.find(f".//{{{WP}}}anchor")) == original


@pytest.mark.parametrize("offset", [12700, -12700])
def test_non_top_positioned_objects_keep_full_geometry_protection(tmp_path, offset):
    """非页顶定位仍可能依赖正文留白，不放松其前后段落及分页规则"""
    doc = Document()
    drawing_paragraph(doc, floating=True, offset=offset)
    paragraph = doc.add_paragraph("定位对象旁的完整正文")
    paragraph.paragraph_format.space_before = Pt(40)
    paragraph.paragraph_format.page_break_before = True
    package = compact(doc, tmp_path, spacing_factor=0, font_scale=0.5, relax_pagination=True)
    paragraph = package.parts["word/document.xml"].findall("w:body/w:p", NS)[1]
    assert paragraph.find("w:pPr/w:spacing", NS).get(w("before")) == "800"
    assert paragraph.find("w:pPr/w:pageBreakBefore", NS).get(w("val"), "1") == "1"
    assert sz(paragraph, "w:pPr/w:rPr/w:sz") >= 11
