"""将依赖绝对位置和分栏的重复条目整理为继承原字体的自然排版。"""

from copy import deepcopy

from lxml import etree

from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.template_map import IMAGE_TAGS, paragraph_text


def effective_section(node):
    """取得当前位置实际使用的节属性，Word 将它保存在当前节的结束位置。"""
    sections = node.xpath(".//w:sectPr | following::w:sectPr[1]", namespaces=NS)
    return sections[0] if sections else None


def requires_flow(sample) -> bool:
    """分栏和浮动文本框不能直接多次复制；含独立装饰图片的样本仍保留原结构。"""
    if any(child.tag in IMAGE_TAGS for node in sample for child in node.iter()):
        return False
    sections = [effective_section(sample[0])]
    sections.extend(section for node in sample for section in node.iter(w("sectPr")))
    return any(
        section is not None
        and section.find(w("cols")) is not None
        and section.find(w("cols")).get(w("num"), "1") != "1"
        for section in sections
    ) or any(node.xpath(".//w:txbxContent", namespaces=NS) for node in sample)


def flow_paragraph(text, donor, align="left"):
    """继承样本字体和文字样式，清除绝对段落定位，允许内容自然换行。"""
    paragraph = etree.Element(w("p"))
    properties = donor.find(w("pPr")) if donor is not None else None
    properties = deepcopy(properties) if properties is not None else etree.Element(w("pPr"))
    for child in list(properties):
        if child.tag in {
            w(name)
            for name in (
                "sectPr",
                "framePr",
                "ind",
                "tabs",
                "spacing",
                "jc",
                "keepNext",
                "pageBreakBefore",
            )
        }:
            properties.remove(child)
    etree.SubElement(properties, w("jc")).set(w("val"), align)
    spacing = etree.SubElement(properties, w("spacing"))
    spacing.set(w("after"), "70")
    spacing.set(w("line"), "240")
    spacing.set(w("lineRule"), "auto")
    paragraph.append(properties)
    style = donor.find(".//w:rPr", NS) if donor is not None else None
    run = etree.SubElement(paragraph, w("r"))
    if style is not None:
        run.append(deepcopy(style))
    for index, line in enumerate(text.split("\n")):
        if index:
            etree.SubElement(run, w("br"))
        node = etree.SubElement(run, w("t"))
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        node.text = line
    return paragraph


def flow_record(package, region, record, keep):
    """复杂栏目使用名称与时间同排、正文在下的条目，保留已映射字段与字体。"""
    donors = {}
    for binding in region.fields:
        donors.setdefault(binding.target, package.node(binding.node))
    nodes = []
    table = etree.Element(w("tbl"))
    properties = etree.SubElement(table, w("tblPr"))
    width = etree.SubElement(properties, w("tblW"))
    width.set(w("w"), "5000")
    width.set(w("type"), "pct")
    borders = etree.SubElement(properties, w("tblBorders"))
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        etree.SubElement(borders, w(side)).set(w("val"), "nil")
    row = etree.SubElement(table, w("tr"))
    for field, align, percent in (("title", "left", "3500"), ("period", "right", "1500")):
        cell = etree.SubElement(row, w("tc"))
        cell_width = etree.SubElement(etree.SubElement(cell, w("tcPr")), w("tcW"))
        cell_width.set(w("w"), percent)
        cell_width.set(w("type"), "pct")
        cell.append(
            flow_paragraph(
                str(record.get(field, "")) if field in donors else "", donors.get(field), align
            )
        )
    nodes.append(table)
    for field in (
        "subtitle",
        "role",
        "stack",
        "description",
        "details",
        "highlights",
        "custom_fields",
    ):
        value = str(record.get(field, "")) if field in donors else ""
        if not value:
            continue
        if field == "role":
            value = "担任角色：" + value
        elif field == "stack":
            value = "技术栈：" + value
        nodes.append(flow_paragraph(value, donors[field]))
    mapped = {field.node for field in region.fields}
    sample_ids = package.descendants(package.region(region.sample_start, region.sample_end))
    for identifier in keep:
        if identifier in mapped or identifier not in sample_ids:
            continue
        donor = package.node(identifier)
        text = paragraph_text(donor) if donor.tag == w("p") else ""
        if text.strip() and not text.rstrip().endswith((":", "：")):
            nodes.append(flow_paragraph(text, donor))
    return nodes
