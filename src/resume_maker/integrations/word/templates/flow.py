"""读取原生节属性并为新增字段继承附近文字样式"""

from copy import deepcopy

from lxml import etree

from resume_maker.integrations.word.ooxml import NS, w


def effective_section(node):
    """取得当前位置实际使用的节属性，Word 将它保存在当前节的结束位置"""
    sections = node.xpath(".//w:sectPr | following::w:sectPr[1]", namespaces=NS)
    return sections[0] if sections else None


def continuous_section(properties):
    """栏目使用连续分节，保留纸张、页边距和列宽且仅取消另起页的默认行为"""
    kind = properties.find(w("type"))
    if kind is None:
        kind = etree.Element(w("type"))
        following = properties.find(w("pgSz"))
        properties.insert(properties.index(following) if following is not None else 0, kind)
    kind.set(w("val"), "continuous")


def continuous_block(block):
    """栏目顺接前文，覆盖段落样式的段前分页并清除硬分页，保留普通换行和分栏"""
    for paragraph in block.iter(w("p")):
        properties = paragraph.find(w("pPr"))
        if properties is None:
            properties = etree.Element(w("pPr"))
            paragraph.insert(0, properties)
        before = properties.find(w("pageBreakBefore"))
        if before is None:
            before = etree.Element(w("pageBreakBefore"))
            previous = [w(tag) for tag in ("pStyle", "keepNext", "keepLines")]
            position = max(
                (properties.index(node) + 1 for node in properties if node.tag in previous),
                default=0,
            )
            properties.insert(position, before)
        before.set(w("val"), "0")
    for node in block.xpath(".//w:br[@w:type='page'] | .//w:lastRenderedPageBreak", namespaces=NS):
        node.getparent().remove(node)
    for properties in block.iter(w("sectPr")):
        continuous_section(properties)
    # 文档末尾的 sectPr 也定义最后一节如何开始，未指定 type 时 Word 默认另起一页
    properties = effective_section(block)
    if properties is not None:
        continuous_section(properties)


def flow_paragraph(text, donor, align="left"):
    """继承样本字体和文字样式，清除绝对段落定位，允许内容自然换行"""
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
