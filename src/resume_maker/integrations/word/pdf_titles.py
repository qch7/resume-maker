"""为 PDF 栏目标题的可编辑文字和背后底块共同预留空间。"""

import math

from lxml import etree

from resume_maker.integrations.word.ooxml import w
from resume_maker.integrations.word.pdf_geometry import WP, recovered_layout
from resume_maker.integrations.word.template_entry_layout import ParagraphStyles
from resume_maker.integrations.word.template_map import paragraph_text
from resume_maker.integrations.word.template_record_columns import (
    content_width,
    font_size,
    text_width,
)


def fit_pdf_titles(package, fields):
    """仅调整 PDF 标题底块和占用高度，新增栏目正文不会挤入底块，长标题可扩展或换行。"""
    if not recovered_layout(package.parts["word/document.xml"]):
        return
    styles = ParagraphStyles(package)
    visited = set()
    for field in fields:
        if not field.target.startswith("section-title:"):
            continue
        paragraph = package.node(field.node)
        if paragraph in visited or paragraph.getparent() is None:
            continue
        visited.add(paragraph)
        available = content_width(styles, paragraph)
        if not available:
            continue
        size = font_size(styles, paragraph)
        needed = text_width(paragraph_text(paragraph), size)
        properties = paragraph.find(w("pPr"))
        if properties is None:
            continue
        spacing = properties.find(w("spacing"))
        if spacing is None:
            spacing = etree.SubElement(properties, w("spacing"))
        before = int(spacing.get(w("before"), "0"))
        rule = spacing.get(w("lineRule"), "auto")
        line = int(spacing.get(w("line"), str(round(size * 24))))
        if rule == "auto":
            line = round(size * 24 * line / 240)
        indent = styles.attributes(paragraph, "w:ind")
        for anchor in paragraph.iter(f"{{{WP}}}anchor"):
            horizontal = anchor.find(f"{{{WP}}}positionH")
            vertical = anchor.find(f"{{{WP}}}positionV")
            extent = anchor.find(f"{{{WP}}}extent")
            if horizontal is None or vertical is None or extent is None:
                continue
            if (
                horizontal.get("relativeFrom") != "column"
                or vertical.get("relativeFrom") != "paragraph"
            ):
                continue
            width, height = int(extent.get("cx", "0")) / 635, int(extent.get("cy", "0")) / 635
            if width < size * 40 or height < size * 15:
                continue
            x = int(horizontal.findtext(f"{{{WP}}}posOffset", "0")) / 635
            padding = max(0, int(indent.get(w("left"), "0")) - x)
            capacity = max(1, available - 120)
            rows = max(1, math.ceil(needed / capacity))
            target_width = min(
                available + padding, max(width, min(needed, capacity) + padding + 120)
            )
            target_height = height + (rows - 1) * line
            for node in anchor.iter():
                if node is extent or node.tag.endswith("}ext") and "cx" in node.attrib:
                    node.set("cx", str(round(target_width * 635)))
                    node.set("cy", str(round(target_height * 635)))
            y = int(vertical.findtext(f"{{{WP}}}posOffset", "0")) / 635
            after = max(
                int(spacing.get(w("after"), "0")),
                math.ceil(y + target_height - before - line * rows + 60),
            )
            spacing.set(w("after"), str(after))
            spacing.set(w("lineRule"), "atLeast")
            spacing.set(w("line"), str(line))
