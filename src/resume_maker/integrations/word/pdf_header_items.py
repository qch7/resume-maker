"""从已确认的 PDF 映射提取顶部资料条目，保留样式并绑定各自图标。"""

import json
import re
from collections import defaultdict
from copy import deepcopy

from resume_maker.core.errors import Problem
from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.pdf_geometry import ROLE, TEXT, WP, rectangle
from resume_maker.integrations.word.template_layout import child_in
from resume_maker.integrations.word.template_map import paragraph_text, quote_range
from resume_maker.integrations.word.template_personal import personal_items

NAMESPACES = {**NS, "wp": WP}


def header_region(package, plan):
    """只选首栏目之前且属于同一正文容器的个人区，不扁平化侧栏或混合栏目。"""
    body = package.parts["word/document.xml"].find(w("body"))
    boundaries = [region.start for region in plan.repeats]
    boundaries.extend(f.node for f in plan.fields if f.target.startswith("section-title:"))
    edge = min(
        (
            body.index(child_in(package.node(key), body))
            for key in boundaries
            if body in package.node(key).iterancestors()
        ),
        default=len(body) - 1,
    )
    fields = [
        f
        for f in plan.fields
        if f.target.startswith("personal.")
        and body in package.node(f.node).iterancestors()
        and body.index(child_in(package.node(f.node), body)) < edge
    ]
    if len(fields) < 2:
        return body, [], []
    keys = [f.node for f in fields] + [
        key
        for key in plan.photos
        if body in package.node(key).iterancestors()
        and body.index(child_in(package.node(key), body)) < edge
    ]
    positions = [body.index(child_in(package.node(key), body)) for key in keys]
    roots = list(body)[min(positions) : max(positions) + 1]
    if any(
        root.xpath(".//w:sectPr | .//w:txbxContent | .//w:fldChar", namespaces=NS) for root in roots
    ):
        raise Problem("PDF 顶部资料区跨分节或固定文本框，无法安全自动重排，请调整模板结构。")
    return body, roots, fields


def without_drawings(paragraph):
    """复制可编辑文字样式，图标和照片另行关联，避免复制片段时带入其他字段的图片。"""
    fragment = deepcopy(paragraph)
    for node in fragment.xpath(".//w:drawing | .//w:pict | .//w:object", namespaces=NS):
        node.getparent().remove(node)
    return fragment


def field_box(paragraph, field):
    """用来源文字片段定位字段；没有来源数据的旧快照只使用原段落归属。"""
    try:
        spans = json.loads(paragraph.get(TEXT, "[]"))
        text = "".join(value for value, _ in spans)
        start, end = quote_range(text, field)
        position, boxes = 0, []
        for value, box in spans:
            if position < end and start < position + len(value):
                boxes.append(box)
            position += len(value)
        if boxes:
            return (
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            )
    except (Problem, ValueError, TypeError):
        pass
    return rectangle(paragraph)


def extract_items(package, roots, fields):
    """按映射提取完整标签和值，无法划分的混合文字明确报错，避免静默丢失原文。"""
    bindings = defaultdict(list)
    for field in fields:
        bindings[package.node(field.node)].append(field)
    items = []
    for root in roots:
        for paragraph in root.iter(w("p")):
            mapped = bindings.get(paragraph, [])
            if not mapped:
                if paragraph_text(paragraph).strip() and not re.fullmatch(
                    r"[\s|｜·•;；]+", paragraph_text(paragraph)
                ):
                    raise Problem("PDF 顶部资料区仍有未关联到字段的文字，请先补全该区域映射。")
                continue
            plain = without_drawings(paragraph)
            parsed = personal_items(plain, mapped) if len(mapped) > 1 else None
            if len(mapped) == 1:
                fragments = [(plain, mapped[0], 0)]
            elif parsed is not None:
                fragments = parsed[0]
            else:
                raise Problem("PDF 同行个人资料的边界不明确，请把各字段完整映射后重试。")
            for fragment, field, _ in fragments:
                items.append(
                    {
                        "paragraph": paragraph,
                        "fragment": fragment,
                        "field": field,
                        "box": field_box(paragraph, field),
                        "icons": [],
                    }
                )
    return items


def drawing_box(anchor):
    """兼容旧 PDF 恢复图形的坐标，以同栏的局部偏移识别重叠小图和左右照片。"""
    box = rectangle(anchor)
    if box is not None:
        return box
    extent = anchor.find(f"{{{WP}}}extent")
    if extent is None:
        return None
    try:
        x = float(anchor.findtext(f"{{{WP}}}positionH/{{{WP}}}posOffset", "0")) / 12700
        y = float(anchor.findtext(f"{{{WP}}}positionV/{{{WP}}}posOffset", "0")) / 12700
        return x, y, x + int(extent.get("cx")) / 12700, y + int(extent.get("cy")) / 12700
    except (ValueError, TypeError):
        return None


def icon_owner(anchor, items):
    """优先同段落与同行右侧字段，多个字段同段时使用来源坐标区分，不按图标外观猜语义。"""
    paragraph = next(anchor.iterancestors(w("p")), None)
    candidates = [item for item in items if item["paragraph"] is paragraph]
    box = rectangle(anchor)
    if len(candidates) == 1:
        return candidates[0]
    if box is not None:
        positioned = [item for item in candidates or items if item["box"] is not None]
        if positioned:

            def distance(item):
                """以纵向重叠为首要条件，再按图标右侧文字的距离选择字段。"""
                rect = item["box"]
                vertical = max(rect[1] - box[3], box[1] - rect[3], 0)
                horizontal = abs(rect[0] - box[2]) + (100 if rect[2] < box[0] else 0)
                return vertical * 10 + horizontal

            return min(positioned, key=distance)
    if candidates:
        raise Problem("PDF 同段多个资料字段缺少图标位置证据，请从源 PDF 重新识别。")
    raise Problem("PDF 顶部图标没有可确认的资料字段，请补全映射后重试。")


def attach_header_assets(package, plan, roots, items):
    """分开处理照片、分隔线和局部图标，隐藏字段不会留下孤立图标。"""
    photos, lines, backgrounds = [], [], []
    photo_nodes = [package.node(key) for key in plan.photos]
    for root in roots:
        for anchor in root.iter(f"{{{WP}}}anchor"):
            role = anchor.get(ROLE)
            box = drawing_box(anchor)
            if box is None:
                raise Problem("PDF 顶部图片缺少有效尺寸，无法安全安排资料区。")
            width, height = box[2] - box[0], box[3] - box[1]
            if any(anchor is node or anchor in node.iterancestors() for node in photo_nodes):
                photos.append(anchor)
            elif (
                role == "background" or anchor.find(f"{{{WP}}}docPr").get("descr") == "PDF 页面底色"
            ):
                backgrounds.append(anchor)
            elif width > height * 8 and height <= 8:
                lines.append(anchor)
            elif width <= 30 and height <= 30:
                icon_owner(anchor, items)["icons"].append(anchor)
            else:
                raise Problem("PDF 顶部包含无法归属的照片或大图形，请确认照片映射后重试。")
    if len(photos) > 1:
        raise Problem("PDF 顶部存在多张资料照片，请确认应使用的照片位置。")
    for item in items:
        icons = item["icons"]
        item["icons"] = [
            anchor
            for index, anchor in enumerate(icons)
            if not any(
                index != other_index
                and contains(drawing_box(other), drawing_box(anchor))
                and (drawing_box(other) != drawing_box(anchor) or other_index < index)
                for other_index, other in enumerate(icons)
            )
        ]
    return photos, lines, backgrounds


def contains(outer, inner):
    """组合裁图已包含内部小路径时只保留整图，防止一个电话图标被重复画两次。"""
    return (
        outer is not None
        and inner is not None
        and (
            outer[0] <= inner[0]
            and outer[1] <= inner[1]
            and outer[2] >= inner[2]
            and outer[3] >= inner[3]
        )
    )
