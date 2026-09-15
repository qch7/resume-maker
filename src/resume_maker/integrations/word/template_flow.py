"""读取原生节属性，并为新增字段继承附近文字样式。"""

from copy import deepcopy

from lxml import etree

from resume_maker.integrations.word.ooxml import NS, w


def effective_section(node):
    """取得当前位置实际使用的节属性，Word 将它保存在当前节的结束位置。"""
    sections = node.xpath(".//w:sectPr | following::w:sectPr[1]", namespaces=NS)
    return sections[0] if sections else None


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
