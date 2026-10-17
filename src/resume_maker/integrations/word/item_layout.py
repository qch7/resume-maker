"""在精确填充处绑定文字身份，完成克隆及重排后按身份应用逐项排版"""

import json
import math
from copy import deepcopy

from lxml import etree

from resume_maker.domain.page_layout import item_key, item_kind, item_style
from resume_maker.integrations.word.compact_flow import (
    compact_flow,
    positioned_content,
    text_only,
    top_positioned_boundary,
)
from resume_maker.integrations.word.ooxml import NS, w

ITEM = "{urn:resume-maker:item-layout}item"
BREAK = "{urn:resume-maker:item-layout}break"


def reference(parts, kind=None):
    """语义引用只含稳定身份，不使用文案、修订或数组位置"""
    return {"key": item_key(*parts), "kind": kind or item_kind(parts[-1])}


def mark_run(run, ref, *, boundary=False):
    """运行携带临时身份，深拷贝、补位及 PDF 顶部重排会自然保留"""
    if ref:
        run.set(ITEM, json.dumps(ref, ensure_ascii=False))
    if boundary:
        run.set(BREAK, "1")


def child(parent, name):
    """保留现有属性，仅补足要覆盖的节点"""
    node = parent.find(w(name))
    if node is None:
        node = etree.Element(w(name))
        parent.insert(0, node) if name in {"pPr", "rPr"} else parent.append(node)
    return node


def split_items(root, options):
    """仅将填充器明确允许的聚合字段拆段，复杂混排继续使用原段落"""
    for paragraph in list(root.iter(w("p"))):
        boundaries = [run for run in paragraph.findall(w("r")) if run.get(BREAK)]
        if not boundaries:
            continue
        declarations = [
            json.loads(run.get(ITEM)) for run in paragraph.findall(w("r")) if run.get(ITEM)
        ]
        if not any(
            set(item_style(options, ref["key"], ref["kind"]))
            & {"space_before", "space_after", "line_spacing"}
            for ref in declarations
        ):
            continue
        if paragraph.xpath(
            ".//w:drawing | .//w:pict | .//w:object | w:pPr/w:sectPr | w:pPr/w:framePr",
            namespaces=NS,
        ):
            continue
        parent = paragraph.getparent()
        if parent is None:
            continue
        current = paragraph
        properties = paragraph.find(w("pPr"))
        for node in list(paragraph):
            if node in boundaries:
                current = etree.Element(w("p"))
                if properties is not None:
                    current.append(deepcopy(properties))
                parent.insert(parent.index(paragraph) + 1, current)
                paragraph = current
                # 分隔运行只携带换行，不属于任一条目的可见内容
                node.getparent().remove(node)
            elif current is not paragraph or node.getparent() is not current:
                if node.tag != w("pPr"):
                    current.append(node)


def style_properties(definitions, identifier, tag, visited=None):
    """按继承链合并原模板样式属性，自动压页以实际参数为起点"""
    visited = set() if visited is None else visited
    if identifier in visited or identifier not in definitions:
        return {}
    visited.add(identifier)
    definition = definitions[identifier]
    parent = definition.find(w("basedOn"))
    result = (
        style_properties(definitions, parent.get(w("val")), tag, visited)
        if parent is not None
        else {}
    )
    properties = definition.find(tag, NS)
    if properties is not None:
        result.update(properties.attrib)
    return result


def scaled_size(size, options):
    """旧减字号先按原边界解析，再统一缩放，六磅以下的原文字保持更小值"""
    legacy = min(size, max(9, size - options.font_delta))
    if options.font_scale == 1 or legacy < 6:
        return legacy
    return math.floor(min(legacy, max(6, legacy * options.font_scale)) * 2) / 2


def set_size(properties, size):
    """正文、复杂文字及段落标记共用半磅精度，避免隐藏字号撑高行框"""
    for name in ("sz", "szCs"):
        child(properties, name).set(w("val"), str(round(size * 2)))


def fit_textboxes(root, options):
    """手工改变文本框内文字时启用随文字伸展，避免放大字号后被原固定框裁切"""
    for content in root.iter(w("txbxContent")):
        changed = any(
            item_style(options, ref["key"], ref["kind"])
            for run in content.iter(w("r"))
            if run.get(ITEM)
            for ref in [json.loads(run.get(ITEM))]
        )
        if not changed:
            continue
        textbox = content.getparent()
        if textbox.tag == "{urn:schemas-microsoft-com:vml}textbox":
            declarations = dict(
                pair.split(":", 1) for pair in textbox.get("style", "").split(";") if ":" in pair
            )
            declarations["mso-fit-shape-to-text"] = "t"
            textbox.set("style", ";".join(f"{key}:{value}" for key, value in declarations.items()))
        else:
            shape = next(
                (node for node in content.iterancestors() if etree.QName(node).localname == "wsp"),
                None,
            )
            if shape is not None:
                body = next(
                    (node for node in shape if etree.QName(node).localname == "bodyPr"), None
                )
                if body is not None:
                    for node in list(body):
                        if etree.QName(node).localname in {"noAutofit", "normAutofit", "spAutoFit"}:
                            body.remove(node)
                    etree.SubElement(
                        body, "{http://schemas.openxmlformats.org/drawingml/2006/main}spAutoFit"
                    )


def reserve_inline_clearance(root, definitions, base_size):
    """独立绘图按后段文字的半字号保留下缘占位，紧行距及自然换页时不让字形侵入图形"""
    default = next(
        (
            key
            for key, style in definitions.items()
            if style.get(w("type")) == "paragraph" and style.get(w("default")) == "1"
        ),
        "Normal",
    )
    for paragraph in root.iter(w("p")):
        runs = [
            run
            for run in paragraph.iter(w("r"))
            if next(run.iterancestors(w("p")), None) is paragraph
        ]
        if any((node.text or "").strip() for run in runs for node in run.findall(w("t"))):
            continue
        inlines = [
            inline
            for run in runs
            for inline in run.xpath("./w:drawing/*[local-name()='inline']", namespaces=NS)
        ]
        if not inlines:
            continue
        following = paragraph.getnext()
        while following is not None and not isinstance(following.tag, str):
            following = following.getnext()
        if following is None or following.tag != w("p"):
            continue
        style = following.find("w:pPr/w:pStyle", NS)
        identifier = style.get(w("val")) if style is not None else default
        inherited = style_properties(definitions, identifier, "w:rPr/w:sz")
        size = float(inherited.get(w("val"), base_size * 2)) / 2
        sizes = []
        for run in following.iter(w("r")):
            if next(run.iterancestors(w("p")), None) is not following or not any(
                (node.text or "").strip() for node in run.findall(w("t"))
            ):
                continue
            character = run.find("w:rPr/w:rStyle", NS)
            inherited = (
                style_properties(definitions, character.get(w("val")), "w:rPr/w:sz")
                if character is not None
                else {}
            )
            actual = run.find("w:rPr/w:sz", NS)
            sizes.append(
                float(
                    actual.get(w("val"))
                    if actual is not None
                    else inherited.get(w("val"), size * 2)
                )
                / 2
            )
        if not sizes:
            continue
        padding = math.ceil(max(sizes) * 0.5 * 12700)
        for inline in inlines:
            extent = inline.find("{*}extent")
            if extent is None:
                continue
            effect = inline.find("{*}effectExtent")
            if effect is None:
                effect = etree.Element(f"{{{etree.QName(inline).namespace}}}effectExtent")
                inline.insert(inline.index(extent) + 1, effect)
                effect.attrib.update(dict.fromkeys(("l", "t", "r", "b"), "0"))
            # 图形自身尺寸不变；占位取最大值以保留已有阴影，重复处理也不累加
            effect.set("b", str(max(int(effect.get("b", "0")), padding)))


def apply_items(root, styles, options):
    """按运行身份设置字号，共段显式间距取最大值，最后执行有界压缩"""
    definitions = (
        {node.get(w("styleId")): node for node in styles.findall(w("style"))}
        if styles is not None
        else {}
    )
    default_size = (
        styles.find("w:docDefaults/w:rPrDefault/w:rPr/w:sz", NS) if styles is not None else None
    )
    base_size = float(default_size.get(w("val"), "22")) / 2 if default_size is not None else 11
    default_spacing = (
        styles.find("w:docDefaults/w:pPrDefault/w:pPr/w:spacing", NS)
        if styles is not None
        else None
    )
    split_items(root, options)
    positioned = positioned_content(root)
    boundary = top_positioned_boundary(root) if positioned else None
    past_boundary = False
    flow_started = False
    if options.auto_fit and options.auto_fit.relax_pagination:
        compact_flow(root, definitions)
    for paragraph in root.iter(w("p")):
        if paragraph is boundary:
            past_boundary = True
        pstyle = paragraph.find("w:pPr/w:pStyle", NS)
        identifier = pstyle.get(w("val")) if pstyle is not None else "Normal"
        inherited = style_properties(definitions, identifier, "w:rPr/w:sz")
        psize = float(inherited.get(w("val"), base_size * 2)) / 2
        paragraph_size = paragraph.find("w:pPr/w:rPr/w:sz", NS)
        marker_base = (
            float(paragraph_size.get(w("val"), psize * 2)) / 2
            if paragraph_size is not None
            else psize
        )
        spacing_values = {}
        maximum_size = 0
        runs = [
            run
            for run in paragraph.iter(w("r"))
            if next(run.iterancestors(w("p")), None) is paragraph
        ]
        has_text = any((node.text or "").strip() for run in runs for node in run.findall(w("t")))
        eligible = (
            past_boundary
            and paragraph is not boundary
            and not any(
                ancestor.tag in {w("txbxContent"), w("drawing"), w("pict"), w("object")}
                for ancestor in paragraph.iterancestors()
            )
        )
        if eligible and has_text:
            flow_started = True
        plain = (not positioned or eligible and flow_started) and text_only(paragraph)
        for run in runs:
            ref = json.loads(run.get(ITEM)) if run.get(ITEM) else None
            explicit = item_style(options, ref["key"], ref["kind"]) if ref else {}
            for name in ("space_before", "space_after", "line_spacing"):
                if name in explicit:
                    spacing_values[name] = max(spacing_values.get(name, 0), explicit[name])
            size = explicit.get("font_size")
            if options.auto_fit:
                character = run.find("w:rPr/w:rStyle", NS)
                inherited = (
                    style_properties(definitions, character.get(w("val")), "w:rPr/w:sz")
                    if character is not None
                    else {}
                )
                node = run.find("w:rPr/w:sz", NS)
                actual = (
                    size
                    if size is not None
                    else float(
                        node.get(w("val"))
                        if node is not None
                        else inherited.get(w("val"), psize * 2)
                    )
                    / 2
                )
                size = scaled_size(actual, options.auto_fit)
                if any((node.text or "").strip() for node in run.findall(w("t"))):
                    maximum_size = max(maximum_size, size)
            if size is not None:
                set_size(child(run, "rPr"), size)
        if options.auto_fit:
            marker_size = maximum_size or scaled_size(marker_base, options.auto_fit)
            if not plain:
                marker_size = max(marker_size, marker_base)
            elif not has_text:
                marker_size = min(
                    marker_size, max(1, marker_size * options.auto_fit.spacing_factor)
                )
            set_size(child(child(paragraph, "pPr"), "rPr"), marker_size)
            for run in runs:
                if not any((node.text or "").strip() for node in run.findall(w("t"))):
                    set_size(child(run, "rPr"), marker_size)
            maximum_size = max(maximum_size, marker_size)
        compress_spacing = options.auto_fit if plain else None
        if spacing_values or compress_spacing:
            spacing = child(child(paragraph, "pPr"), "spacing")
            original = dict(default_spacing.attrib) if default_spacing is not None else {}
            original.update(style_properties(definitions, identifier, "w:pPr/w:spacing"))
            original.update(spacing.attrib)
            for prop, attr in (("space_before", "before"), ("space_after", "after")):
                amount = spacing_values.get(prop)
                if amount is not None or compress_spacing:
                    amount = (
                        amount if amount is not None else float(original.get(w(attr), "0")) / 20
                    )
                    if compress_spacing:
                        amount *= compress_spacing.spacing_factor
                    spacing.set(w(attr), str(round(amount * 20)))
                    spacing.attrib.pop(w(attr + "Autospacing"), None)
                    spacing.attrib.pop(w(attr + "Lines"), None)
            line = spacing_values.get("line_spacing")
            if line is not None:
                original[w("lineRule")] = "auto"
            if compress_spacing:
                rule = original.get(w("lineRule"), "auto")
                if line is None and rule == "auto":
                    line = float(original.get(w("line"), "240")) / 240
                if line is not None:
                    line = min(line, 1 + (line - 1) * compress_spacing.spacing_factor)
                elif rule in {"exact", "atLeast"} and w("line") in original:
                    # 固定行距保留最大字号的 1.2 倍行框，本来更小的人工行距不放大
                    original_line = float(original[w("line")])
                    tightened = min(
                        original_line,
                        max(maximum_size * 24, original_line * compress_spacing.spacing_factor),
                    )
                    spacing.set(w("line"), str(round(tightened)))
                    spacing.set(w("lineRule"), rule)
            if line is not None:
                spacing.set(w("line"), str(round(line * 240)))
                spacing.set(w("lineRule"), "auto")
    fit_textboxes(root, options)
    reserve_inline_clearance(root, definitions, base_size)
    for node in root.iter():
        node.attrib.pop(ITEM, None)
        node.attrib.pop(BREAK, None)
