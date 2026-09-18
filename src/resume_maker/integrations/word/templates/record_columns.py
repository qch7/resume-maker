"""将重复条目中靠空格推开的元信息转成稳定列宽；长标题在自己的列内换行"""

import re
import unicodedata
from collections import defaultdict

from lxml import etree

from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.templates.flow import effective_section
from resume_maker.integrations.word.templates.mapping import paragraph_text, quote_range
from resume_maker.integrations.word.templates.personal import paragraph_stream, slice_paragraph


def content_width(styles, paragraph):
    """从本单元格或本节取得可用宽度；未知宽度、分栏和绝对定位不猜测页面坐标"""
    if styles.group(paragraph) is None:
        return None
    if next(paragraph.iterancestors(w("txbxContent")), None) is not None:
        return None
    parent = paragraph.getparent()
    cell = next(paragraph.iterancestors(w("tc")), None)
    if cell is not None:
        parent = cell
    if parent.tag == w("tc"):
        node = parent.find("w:tcPr/w:tcW", NS)
        if node is None or node.get(w("type")) != "dxa":
            return None
        width = int(node.get(w("w"), "0"))
        margins = parent.find("w:tcPr/w:tcMar", NS)
        for side in ("left", "right"):
            margin = margins.find(w(side)) if margins is not None else None
            width -= int(margin.get(w("w"), "108")) if margin is not None else 108
    elif parent.tag in {w("body"), w("sdtContent")}:
        section = effective_section(paragraph)
        page = section.find(w("pgSz")) if section is not None else None
        margins = section.find(w("pgMar")) if section is not None else None
        if page is None or margins is None:
            return None
        width = int(page.get(w("w"), "0"))
        width -= sum(int(margins.get(w(key), "0")) for key in ("left", "right", "gutter"))
    else:
        return None
    indent = styles.attributes(paragraph, "w:ind")
    if any(w(key) in indent for key in ("leftChars", "rightChars", "startChars", "endChars")):
        return None
    width -= sum(int(indent.get(w(key), "0")) for key in ("left", "right"))
    return width if width > 0 else None


def text_width(text, size):
    """保守估算中英文混排宽度且只用于分配列宽；实际换行仍由 Word 完成"""
    return round(
        sum(
            1
            if unicodedata.east_asian_width(char) in {"W", "F"}
            else 0.35
            if char.isspace()
            else 0.65
            for char in text
        )
        * size
        * 20
        * 1.12
    )


def font_size(styles, paragraph):
    """读取运行和继承样式中的字号上界以免日期标签比数值大时低估宽度"""
    sizes = paragraph.xpath(".//w:sz/@w:val", namespaces=NS)
    for properties in styles.properties(paragraph):
        if properties.getparent().tag == w("style"):
            sizes.extend(properties.getparent().xpath("w:rPr/w:sz/@w:val", namespaces=NS))
    return max((int(value) / 2 for value in sizes), default=11)


def column_fragments(paragraph, fields):
    """只拆两个已映射元信息之间的排版空白；保留引文内空格、固定标签和超链接"""
    if len(fields) != 2 or {field.target for field in fields} != {"title", "period"}:
        return None
    if paragraph.xpath(
        ".//w:drawing | .//w:pict | .//w:object | .//w:fldChar | .//w:txbxContent "
        "| w:pPr/w:sectPr | .//w:br | .//w:cr",
        namespaces=NS,
    ):
        return None
    text = paragraph_text(paragraph)
    stream, positions = paragraph_stream(paragraph)
    ordered = sorted(fields, key=lambda field: quote_range(text, field))
    if any(not field.quote for field in ordered):
        return None
    ranges = [quote_range(text, field) for field in ordered]
    left_end, right_start = positions[ranges[0][1] - 1] + 1, positions[ranges[1][0]]
    gaps = list(re.finditer(r"[ \u00a0\u3000]{2,}|\t+", stream[left_end:right_start]))
    if not gaps:
        return None
    gap = max(gaps, key=lambda item: item.end() - item.start())
    spans = [(0, left_end + gap.start()), (left_end + gap.end(), len(stream))]
    fragments = []
    for field, (start, end), (quote_start, _) in zip(ordered, spans, ranges, strict=True):
        start += len(stream[start:end]) - len(stream[start:end].lstrip())
        end = start + len(stream[start:end].rstrip())
        fragment = slice_paragraph(paragraph, start, end)
        prefix = stream[start : positions[quote_start]].replace("\t", "").replace("\n", "")
        occurrence = len(list(re.finditer(f"(?={re.escape(field.quote)})", prefix))) + 1
        fragments.append((fragment, field.model_copy(update={"occurrence": occurrence})))
    return fragments, "\t" in gap.group()


def column_paragraph(paragraph, align):
    """单元格内清除旧推移坐标；保留字体、行距与标签字重；固定行高改为最小行高"""
    properties = paragraph.find(w("pPr"))
    if properties is None:
        properties = etree.Element(w("pPr"))
        paragraph.insert(0, properties)
    for tag in ("ind", "tabs", "jc", "numPr"):
        node = properties.find(w(tag))
        if node is not None:
            properties.remove(node)
    indent = etree.SubElement(properties, w("ind"))
    for key in ("left", "right", "firstLine", "hanging", "firstLineChars", "hangingChars"):
        indent.set(w(key), "0")
    etree.SubElement(properties, w("jc")).set(w("val"), align)
    number = etree.SubElement(properties, w("numPr"))
    etree.SubElement(number, w("numId")).set(w("val"), "0")
    spacing = properties.find(w("spacing"))
    if spacing is not None and spacing.get(w("lineRule")) == "exact":
        spacing.set(w("lineRule"), "atLeast")


def make_columns(paragraph, fragments, widths, left):
    """创建无边框固定列宽表格且不设行高或不换行约束；让长标题自然撑高一条记录"""
    table = etree.Element(w("tbl"))
    properties = etree.SubElement(table, w("tblPr"))
    etree.SubElement(properties, w("tblW"), {w("w"): str(sum(widths)), w("type"): "dxa"})
    etree.SubElement(properties, w("tblInd"), {w("w"): str(left), w("type"): "dxa"})
    etree.SubElement(properties, w("tblLayout")).set(w("type"), "fixed")
    borders = etree.SubElement(properties, w("tblBorders"))
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        etree.SubElement(borders, w(side)).set(w("val"), "nil")
    margins = etree.SubElement(properties, w("tblCellMar"))
    for side in ("top", "left", "bottom", "right"):
        etree.SubElement(margins, w(side), {w("w"): "0", w("type"): "dxa"})
    grid = etree.SubElement(table, w("tblGrid"))
    for width in widths:
        etree.SubElement(grid, w("gridCol")).set(w("w"), str(width))
    row = etree.SubElement(table, w("tr"))
    etree.SubElement(etree.SubElement(row, w("trPr")), w("cantSplit"))
    for index, ((fragment, _), width) in enumerate(zip(fragments, widths, strict=True)):
        cell = etree.SubElement(row, w("tc"))
        props = etree.SubElement(cell, w("tcPr"))
        etree.SubElement(props, w("tcW"), {w("w"): str(width), w("type"): "dxa"})
        etree.SubElement(props, w("vAlign")).set(w("val"), "top")
        column_paragraph(fragment, "right" if index else "left")
        if not index:
            fragment.find("w:pPr/w:ind", NS).set(w("right"), "120")
        cell.append(fragment)
    paragraph.getparent().replace(paragraph, table)


def prepare_record_columns(styles, nodes, fields, records, source_nodes=None):
    """每份重复区使用全部记录的最大日期宽度以免短名称、长名称各自生成不同列线"""
    grouped, result = defaultdict(list), list(fields)
    for field in fields:
        grouped[field.node].append(field)
    for identifier, bindings in grouped.items():
        paragraph = nodes[identifier]
        # 克隆暂时插在重复区起点；起点与样本之间可能有分节；必须使用样本原位置的几何
        source = (source_nodes or {}).get(identifier, paragraph)
        width = content_width(styles, source)
        if width is not None:
            old_indent = styles.attributes(source, "w:ind")
            new_indent = styles.attributes(paragraph, "w:ind")
            width -= sum(
                int(new_indent.get(w(key), "0")) - int(old_indent.get(w(key), "0"))
                for key in ("left", "right")
            )
            width = width if width > 0 else None
        parsed = column_fragments(paragraph, bindings) if width else None
        if parsed is None or styles.numbered(paragraph):
            continue
        fragments, tabs = parsed
        size = font_size(styles, paragraph)
        requirements = []
        for fragment, field in fragments:
            text = paragraph_text(fragment)
            start, end = quote_range(text, field)
            requirements.append(
                max(
                    (
                        text_width(
                            text[:start] + str(record.get(field.target, "")) + text[end:], size
                        )
                        for record in records
                    ),
                    default=0,
                )
            )
        stops = {}
        for properties in styles.properties(paragraph):
            for node in properties.findall("w:tabs/w:tab", NS):
                position = int(node.get(w("pos"), "0"))
                stops[position] = node.get(w("val"))
        stops = {pos: kind for pos, kind in stops.items() if kind != "clear"}
        left = int(styles.attributes(paragraph, "w:ind").get(w("left"), "0"))
        if (
            tabs
            and len(stops) == 1
            and next(iter(stops.values())) == "right"
            and sum(requirements) + 240 <= next(iter(stops)) - left <= width
        ):
            continue
        right = max(requirements[1] + 120, round(width * 0.2))
        if right < width * 0.6:
            make_columns(paragraph, fragments, [width - right, right], left)
        else:
            # 极窄容器或很长的元信息统一按两行排列且不再制造更窄的单元格
            for fragment, _ in fragments:
                column_paragraph(fragment, "left")
                paragraph.addprevious(fragment)
            paragraph.getparent().remove(paragraph)
        for index, (fragment, field) in enumerate(fragments):
            key = f"{identifier}-column-{index}"
            nodes[key] = fragment
            original = next(binding for binding in bindings if binding.target == field.target)
            result[result.index(original)] = field.model_copy(update={"node": key})
    return result
