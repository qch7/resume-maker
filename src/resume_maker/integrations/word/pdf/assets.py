"""从 PDF 的独立视觉层提取素材并让装饰随对应 Word 段落移动"""

from io import BytesIO

import pymupdf
from docx.oxml import OxmlElement
from docx.shared import Pt

from resume_maker.integrations.word.pdf.geometry import BOX, ROLE


def page_background(drawing, page):
    """独立识别大面积矩形底色以免它把所有图标和照片合并为一张不可替换的大图"""
    box = pymupdf.Rect(drawing["rect"]) & page.rect
    return (
        drawing.get("fill") is not None
        and len(drawing["items"]) == 1
        and drawing["items"][0][0] == "re"
        and box.get_area() > page.rect.get_area() * 0.15
    )


def background_assets(page):
    """纯色背景独立生成透明素材；其内部不会包含其他图片、图标或旧文字"""
    assets = []
    for drawing in page.get_drawings():
        if not page_background(drawing, page) or min(drawing["fill"]) > 0.97:
            continue
        box = pymupdf.Rect(drawing["rect"]) & page.rect
        with pymupdf.open() as document:
            fill = document.new_page(width=box.width, height=box.height)
            fill.draw_rect(
                fill.rect,
                color=None,
                fill=drawing["fill"],
                fill_opacity=drawing.get("fill_opacity", 1),
            )
            raw = fill.get_pixmap(alpha=True).tobytes("png")
        assets.append((box, None, raw))
    return assets


def asset_regions(page):
    """合并相交的局部绘制与图片；忽略整页白底但保留裁剪、透明和图形组合"""
    regions = []
    for drawing in page.get_drawings():
        if page_background(drawing, page):
            continue
        padding = max(0.5, (drawing.get("width") or 0) / 2)
        # 路径矩形不含笔画宽度；纯水平或垂直线的面积为零；必须先扩到可见笔画再裁切
        box = (pymupdf.Rect(drawing["rect"]) + (-padding, -padding, padding, padding)) & page.rect
        fill = drawing.get("fill")
        if box.is_empty or (
            fill and min(fill) > 0.97 and box.get_area() > page.rect.get_area() * 0.8
        ):
            continue
        regions.append([box, False])
    for item in page.get_image_info():
        box = pymupdf.Rect(item["bbox"]) & page.rect
        if not box.is_empty:
            regions.append([box, True])
    merged = []
    for box, photo in regions:
        # 细长横线不能把整排图标、照片和标题连接成一张大图
        thin = min(box.width, box.height) < 2
        index = 0
        while index < len(merged):
            other, other_photo = merged[index]
            other_thin = min(other.width, other.height) < 2
            if not thin and not other_thin and (box + (-0.5, -0.5, 0.5, 0.5)).intersects(other):
                box |= other
                photo = photo or other_photo
                merged.pop(index)
                index = 0
            else:
                index += 1
        merged.append([box & page.rect, photo])
    return sorted(merged, key=lambda item: (item[0].y0, item[0].x0))


def extract_assets(page):
    """在副本中删除文字再裁图；图片里不残留旧姓名、正文或标题文字"""
    regions = asset_regions(page)
    assets = background_assets(page)
    if not regions:
        return assets
    with pymupdf.open(stream=page.parent.tobytes(), filetype="pdf") as visual:
        clean = visual[page.number]
        clean.add_redact_annot(clean.rect, fill=None)
        clean.apply_redactions(images=0, graphics=0, text=0)
        for photographs in (True, False):
            if not photographs:
                # 横线的裁剪区可能擦过照片边缘；先去掉照片以防裁入一条照片色带
                clean.add_redact_annot(clean.rect, fill=None)
                clean.apply_redactions(images=1, graphics=0, text=1)
            for box, photo in regions:
                if photo != photographs:
                    continue
                scale = min(6.0, (8_000_000 / max(1, box.get_area())) ** 0.5)
                raw = clean.get_pixmap(clip=box, matrix=pymupdf.Matrix(scale, scale), alpha=True)
                assets.append((box, photo, raw.tobytes("png")))
        return assets


def separate_bullets(page, assets):
    """重复出现且紧邻文字左侧的小图形转为列表文字以免空条目留下孤立图片"""
    lines = [
        line
        for block in page.get_text("dict")["blocks"]
        if block["type"] == 0
        for line in block["lines"]
    ]
    candidates = []
    for index, (box, photo, _) in enumerate(assets):
        if photo or not (2 <= box.width <= 6 and 2 <= box.height <= 6):
            continue
        nearby = [
            line
            for line in lines
            if 0 < line["bbox"][0] - box.x1 < 18
            and line["bbox"][1] <= (box.y0 + box.y1) / 2 <= line["bbox"][3]
        ]
        if nearby:
            line = min(nearby, key=lambda item: item["bbox"][0])
            span = line["spans"][0]
            candidates.append((index, box, span))
    selected, bullets = set(), []
    for index, box, span in candidates:
        if sum(abs(other.x0 - box.x0) < 1 for _, other, _ in candidates) >= 3:
            selected.add(index)
            bullets.append(((box.x0 + box.x1) / 2, span["origin"][1], span["size"]))
    return [asset for index, asset in enumerate(assets) if index not in selected], bullets


def attach_asset(paragraph, raw, box, top, column_left, label, layer):
    """把素材放在文字后方；纵坐标相对段落；使栏目重排和重复条目保持图文关联"""
    inline = paragraph.add_run().add_picture(
        BytesIO(raw), width=Pt(box.width), height=Pt(box.height)
    )
    drawing = inline._inline
    anchor = OxmlElement("wp:anchor")
    anchor.set(BOX, str(list(box)))
    anchor.set(ROLE, "background" if layer == 0 else "photo" if layer == 2 else "decoration")
    for key, value in {
        "distT": "0",
        "distB": "0",
        "distL": "0",
        "distR": "0",
        "simplePos": "0",
        # Word 会把接近零的层级重新排序；使用其正常绘图层级区间保持底色、图标和照片顺序
        "relativeHeight": str(251658240 + layer * 1000),
        "behindDoc": "1",
        "locked": "0",
        "layoutInCell": "0",
        "allowOverlap": "1",
    }.items():
        anchor.set(key, value)
    position = OxmlElement("wp:simplePos")
    position.set("x", "0")
    position.set("y", "0")
    anchor.append(position)
    before = paragraph.paragraph_format.space_before
    vertical = box.y0 - top + (before.pt if before is not None else 0)
    positions = (
        (("H", "page", box.x0), ("V", "page", box.y0))
        if layer == 0
        else (("H", "column", box.x0 - column_left), ("V", "paragraph", vertical))
    )
    for axis, relation, offset in positions:
        position = OxmlElement("wp:position" + axis)
        position.set("relativeFrom", relation)
        value = OxmlElement("wp:posOffset")
        value.text = str(round(offset * 12700))
        position.append(value)
        anchor.append(position)
    anchor.append(drawing.extent)
    anchor.append(OxmlElement("wp:wrapNone"))
    drawing.docPr.set("descr", label)
    for child in list(drawing):
        anchor.append(child)
    drawing.getparent().replace(drawing, anchor)


def place_assets(assets, paragraphs):
    """把底色关联覆盖的文字；把图标、照片和分隔线关联最近的段落"""
    for box, photo, raw in assets:

        def distance(item, area=box):
            """优先同高度的段落并用横向距离区分左右栏"""
            _, rect, _ = item
            vertical = max(rect.y0 - area.y1, area.y0 - rect.y1, 0)
            horizontal = max(rect.x0 - area.x1, area.x0 - rect.x1, 0)
            return vertical * 4 + horizontal * 0.15, abs(rect.y0 - area.y0)

        paragraph, rect, column_left = min(paragraphs, key=distance)
        label = (
            "PDF 页面底色"
            if photo is None
            else "PDF 原图或照片"
            if photo
            else "PDF 固定装饰（图标、底色或线条）"
        )
        layer = 0 if photo is None else 2 if photo else 1
        attach_asset(paragraph, raw, box, rect.y0, column_left, label, layer)
