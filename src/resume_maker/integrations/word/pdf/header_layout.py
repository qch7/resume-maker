"""仅对 PDF 恢复模板的顶部资料区按实际字段宽度排版；照片与图标进入真实容器"""

import re
from copy import deepcopy

from lxml import etree

from resume_maker.core.errors import Problem
from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.pdf.geometry import (
    BOX,
    SOURCE,
    WP,
    legacy_asset,
    recovered_layout,
)
from resume_maker.integrations.word.pdf.header_items import (
    attach_header_assets,
    drawing_box,
    extract_items,
    header_region,
)
from resume_maker.integrations.word.templates.contact_style import SLOT_VERSION
from resume_maker.integrations.word.templates.flow import effective_section
from resume_maker.integrations.word.templates.mapping import paragraph_text
from resume_maker.integrations.word.templates.record_columns import column_paragraph, text_width

ORDER = {
    "personal.name": 0,
    "personal.job_title": 1,
    "personal.phone": 2,
    "personal.email": 3,
    "personal.gender": 4,
    "personal.age": 5,
    "personal.gpa": 6,
    "personal.location": 7,
    "personal.website": 8,
}


def paragraph_properties(paragraph):
    """取得段落属性；始终放在文字和绘图之前以生成合法 Word 结构"""
    properties = paragraph.find(w("pPr"))
    if properties is None:
        properties = etree.Element(w("pPr"))
        paragraph.insert(0, properties)
    return properties


def flowing_paragraph(paragraph, title=False):
    """清除 PDF 的固定行高、缩进和制表位；保留文字样式并让长内容自然撑高"""
    alignment = paragraph.find("w:pPr/w:jc", NS)
    align = alignment.get(w("val"), "left") if title and alignment is not None else "left"
    column_paragraph(paragraph, align)
    properties = paragraph_properties(paragraph)
    for name in ("framePr", "keepNext", "keepLines", "pageBreakBefore", "spacing"):
        for node in list(properties.findall(w(name))):
            properties.remove(node)
    etree.SubElement(
        properties,
        w("spacing"),
        {
            w("before"): "0",
            w("after"): "100" if title else "60",
            w("line"): "264",
            w("lineRule"): "auto",
        },
    )
    if title:
        etree.SubElement(properties, w("keepNext"))


def empty_paragraph():
    """表格单元格的必需结束段落仅占极小高度以免人为增加整行空白"""
    paragraph = etree.Element(w("p"))
    etree.SubElement(
        paragraph_properties(paragraph),
        w("spacing"),
        {
            w("before"): "0",
            w("after"): "0",
            w("line"): "1",
            w("lineRule"): "exact",
        },
    )
    return paragraph


def table_cells(widths, *, keep_row=False):
    """创建无边框固定列宽容器；不设固定行高；文字再长也不会覆盖照片或相邻字段"""
    table = etree.Element(w("tbl"))
    properties = etree.SubElement(table, w("tblPr"))
    etree.SubElement(properties, w("tblW"), {w("w"): str(sum(widths)), w("type"): "dxa"})
    etree.SubElement(properties, w("tblLayout"), {w("type"): "fixed"})
    margins = etree.SubElement(properties, w("tblCellMar"))
    for side in ("top", "left", "bottom", "right", "start", "end"):
        etree.SubElement(margins, w(side), {w("w"): "0", w("type"): "dxa"})
    borders = etree.SubElement(properties, w("tblBorders"))
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        etree.SubElement(borders, w(side), {w("val"): "nil"})
    grid = etree.SubElement(table, w("tblGrid"))
    for width in widths:
        etree.SubElement(grid, w("gridCol"), {w("w"): str(width)})
    row = etree.SubElement(table, w("tr"))
    if keep_row:
        etree.SubElement(etree.SubElement(row, w("trPr")), w("cantSplit"))
    cells = []
    for width in widths:
        cell = etree.SubElement(row, w("tc"))
        props = etree.SubElement(cell, w("tcPr"))
        etree.SubElement(props, w("tcW"), {w("w"): str(width), w("type"): "dxa"})
        etree.SubElement(props, w("vAlign"), {w("val"): "top"})
        cells.append(cell)
    return table, cells


def inline_drawing(anchor, width=None):
    """将已填入实际图片的绘图转换为行内对象以免再次依赖旧段落的绝对偏移"""
    drawing = etree.Element(w("drawing"))
    inline = etree.SubElement(
        drawing, f"{{{WP}}}inline", {"distT": "0", "distB": "0", "distL": "0", "distR": "0"}
    )
    for name in ("extent", "effectExtent", "docPr", "cNvGraphicFramePr"):
        child = anchor.find(f"{{{WP}}}{name}")
        if child is not None:
            inline.append(deepcopy(child))
    graphic = next((child for child in anchor if child.tag.endswith("}graphic")), None)
    if graphic is not None:
        inline.append(deepcopy(graphic))
    extent = inline.find(f"{{{WP}}}extent")
    if width is not None and extent is not None:
        scale = width * 635 / int(extent.get("cx"))
        for node in inline.iter():
            if node is extent or node.tag.endswith("}ext") and "cx" in node.attrib:
                node.set("cx", str(round(int(node.get("cx")) * scale)))
                node.set("cy", str(round(int(node.get("cy")) * scale)))
    return drawing


def source_style(items):
    """新增字段使用原 PDF 正文资料字体且不从无文字的图标运行继承 Word 默认字体"""
    ordered = sorted(
        items,
        key=lambda item: (
            item["field"].target not in {"personal.phone", "personal.email"},
            ORDER.get(item["field"].target, 9),
        ),
    )
    for item in ordered:
        if item["paragraph"].get(SLOT_VERSION) or item["field"].target == "personal.name":
            continue
        for run in item["fragment"].iter(w("r")):
            if "".join(run.itertext()).strip():
                style = run.find(w("rPr"))
                if style is not None:
                    style = deepcopy(style)
                    for candidate in items:
                        if candidate["paragraph"].get(SLOT_VERSION):
                            continue
                        for sample in candidate["fragment"].iter(w("r")):
                            if re.search(r"[\u4e00-\u9fff]", "".join(sample.itertext())):
                                fonts = sample.find("w:rPr/w:rFonts", NS)
                                if fonts is not None and fonts.get(w("eastAsia")):
                                    target = style.find(w("rFonts"))
                                    if target is None:
                                        target = etree.SubElement(style, w("rFonts"))
                                    target.set(w("eastAsia"), fonts.get(w("eastAsia")))
                                    return style
                    return style
    return None


def prepare_fragment(item, style):
    """生成资料条目和行内图标；隐藏条目不参加排版；原字段的局部字重保持"""
    fragment = item["fragment"]
    inherited_fonts = style.find(w("rFonts")) if style is not None else None
    if inherited_fonts is not None:
        for fonts in fragment.iter(w("rFonts")):
            if fonts.get(w("eastAsia")) == inherited_fonts.get(w("ascii")):
                fonts.set(
                    w("eastAsia"),
                    inherited_fonts.get(w("eastAsia"), inherited_fonts.get(w("ascii"))),
                )
    if style is not None and item["paragraph"].get(SLOT_VERSION):
        for run in fragment.iter(w("r")):
            old = run.find(w("rPr"))
            if old is not None:
                run.remove(old)
            run.insert(0, deepcopy(style))
    flowing_paragraph(fragment, title=item["field"].target == "personal.name")
    if item.get("alignment"):
        fragment.find("w:pPr/w:jc", NS).set(w("val"), item["alignment"])
    for anchor in reversed(item["icons"]):
        run = etree.Element(w("r"))
        run.append(inline_drawing(anchor))
        etree.SubElement(
            run, w("t"), {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}
        ).text = " "
        fragment.insert(1, run)
    return fragment


def item_width(item):
    """保守计算条目需要的宽度；字号和图标计入预算；最终断行仍交给 Word"""
    paragraph = item["fragment"]
    size = max((int(x) / 2 for x in paragraph.xpath(".//w:sz/@w:val", namespaces=NS)), default=11)
    icon_width = sum(
        (drawing_box(icon)[2] - drawing_box(icon)[0]) * 20 + 60 for icon in item["icons"]
    )
    return round(text_width(paragraph_text(paragraph), size) + icon_width + 180)


def packed_items(items, available):
    """按实际文字宽度放入一行；放不下时整项换行；超长单项独占一行"""
    rows, row, used = [], [], 0
    for item in items:
        width = min(available, item_width(item))
        if row and used + width > available:
            rows.append(row)
            row, used = [], 0
        row.append((item, width))
        used += width
    if row:
        rows.append(row)
    return rows


class PDFHeaderLayout:
    """先捕获已确认资料与图片；再在正式填充结束后重排独立顶部区域"""

    def __init__(self, package, plan, values):
        """普通 Word 立即返回；PDF 只处理不跨栏目的顶部个人资料；保留原模板及映射"""
        self.nodes, self.fields, self.notices, self.roots = {}, [], [], []
        if not recovered_layout(package.parts["word/document.xml"]):
            return
        self.source_label = (
            "图片" if package.parts["word/document.xml"].get(SOURCE) == "image-v1" else "PDF"
        )
        if self.source_label == "图片":
            from resume_maker.integrations.word.image.header import check_image_header

            check_image_header(package, plan)
        body, roots, fields = header_region(package, plan)
        if not roots:
            return
        if not any(
            node.get(BOX) is not None or legacy_asset(node)
            for root in roots
            for node in root.iter()
        ):
            # 混合 PDF 的后续原生页不能改变首页扫描恢复或外部 Word 资料区的处理方式
            return
        items = extract_items(package, roots, fields)
        photos, lines, backgrounds = attach_header_assets(package, plan, roots, items)
        section = effective_section(roots[0])
        page = section.find(w("pgSz")) if section is not None else None
        margins = section.find(w("pgMar")) if section is not None else None
        if page is None or margins is None:
            raise Problem("PDF 顶部资料区缺少页面宽度，无法安全自动排版。")
        self.width = int(page.get(w("w"))) - sum(
            int(margins.get(w(key), "0")) for key in ("left", "right", "gutter")
        )
        columns = section.find(w("cols"))
        if self.width <= 0 or columns is not None and int(columns.get(w("num"), "1")) > 1:
            raise Problem("PDF 顶部资料区处于多栏节中，请先确认独立的顶部资料容器。")
        self.body, self.roots = body, roots
        self.position, self.following = body.index(roots[0]), roots[-1].getnext()
        self.photos = photos if values.get("personal.photo") else []
        self.lines, self.backgrounds = lines, backgrounds
        self.style = deepcopy(source_style(items))
        left = int(margins.get(w("left"), "0")) / 20
        right = (int(page.get(w("w"))) - int(margins.get(w("right"), "0"))) / 20
        for item in items:
            box = item["box"]
            if item["field"].target == "personal.name" and box is not None:
                # 转换器的局部列对齐不能代表页首标题；按来源几何判断左、中、右对齐
                distances = {
                    "left": abs(box[0] - left),
                    "center": abs((box[0] + box[2] - left - right) / 2),
                    "right": abs(box[2] - right),
                }
                item["alignment"] = min(distances, key=distances.get)
        self.items = sorted(
            (item for item in items if values.get(item["field"].target)),
            key=lambda item: ORDER.get(item["field"].target, 9),
        )
        for index, item in enumerate(self.items):
            identifier = f"pdf-header-{index}"
            self.nodes[identifier] = item["fragment"]
            self.fields.append(item["field"].model_copy(update={"node": identifier}))

    def apply(self):
        """将已填值的条目放入可伸展容器；照片留独立列；分隔线跟随整个顶部区域"""
        if not self.roots:
            return
        for item in self.items:
            prepare_fragment(item, self.style)
        photo = self.photos[0] if self.photos else None
        photo_width = (
            min(round((drawing_box(photo)[2] - drawing_box(photo)[0]) * 20), self.width // 4)
            if photo is not None
            else 0
        )
        gap = 240 if photo is not None else 0
        text_width_available = self.width - photo_width - gap
        photo_left = (
            photo is not None
            and (drawing_box(photo)[0] + drawing_box(photo)[2]) * 10 < self.width / 2
        )
        widths = (
            [photo_width + gap, text_width_available]
            if photo_left
            else [text_width_available, photo_width + gap]
        )
        table, cells = table_cells(widths if photo is not None else [self.width])
        text_cell = cells[-1] if photo_left else cells[0]
        for item in self.items:
            if item["field"].target in {"personal.name", "personal.job_title"}:
                text_cell.append(item["fragment"])
        details = [
            item
            for item in self.items
            if item["field"].target not in {"personal.name", "personal.job_title"}
        ]
        for packed in packed_items(details, text_width_available):
            widths = [width for _, width in packed]
            widths[-1] += text_width_available - sum(widths)
            row, slots = table_cells(widths, keep_row=True)
            for (item, _), cell in zip(packed, slots, strict=True):
                cell.append(item["fragment"])
            text_cell.append(row)
        text_cell.append(empty_paragraph())
        if photo is not None:
            paragraph = etree.Element(w("p"))
            flowing_paragraph(paragraph)
            paragraph.find("w:pPr/w:jc", NS).set(w("val"), "left" if photo_left else "right")
            etree.SubElement(paragraph, w("r")).append(inline_drawing(photo, photo_width))
            cells[0 if photo_left else -1].append(paragraph)
        replacements = []
        for anchor in self.backgrounds:
            paragraph = empty_paragraph()
            drawing = etree.SubElement(etree.SubElement(paragraph, w("r")), w("drawing"))
            drawing.append(deepcopy(anchor))
            replacements.append(paragraph)
        if self.items or photo is not None:
            replacements.append(table)
            for anchor in self.lines:
                paragraph = empty_paragraph()
                spacing = paragraph.find("w:pPr/w:spacing", NS)
                spacing.set(
                    w("line"),
                    str(max(20, round((drawing_box(anchor)[3] - drawing_box(anchor)[1]) * 20))),
                )
                spacing.set(w("after"), "80")
                etree.SubElement(paragraph, w("r")).append(inline_drawing(anchor, self.width))
                replacements.append(paragraph)
        for root in self.roots:
            if root.getparent() is self.body:
                self.body.remove(root)
        position = (
            self.body.index(self.following)
            if self.following is not None and self.following.getparent() is self.body
            else min(self.position, len(self.body) - 1)
        )
        for offset, root in enumerate(replacements):
            self.body.insert(position + offset, root)
        self.notices.append(
            f"已按实际内容重排 {self.source_label} 顶部资料，图标跟随字段，"
            "照片独立留位，隐藏资料不留空图标。"
        )
