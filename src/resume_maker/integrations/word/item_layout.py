"""在精确填充处绑定文字身份，完成克隆及重排后按身份应用逐项排版"""

import json
from copy import deepcopy

from lxml import etree

from resume_maker.domain.page_layout import item_key, item_kind, item_style
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
    for paragraph in root.iter(w("p")):
        pstyle = paragraph.find("w:pPr/w:pStyle", NS)
        identifier = pstyle.get(w("val")) if pstyle is not None else "Normal"
        inherited = style_properties(definitions, identifier, "w:rPr/w:sz")
        psize = float(inherited.get(w("val"), base_size * 2)) / 2
        paragraph_size = paragraph.find("w:pPr/w:rPr/w:sz", NS)
        if paragraph_size is not None:
            psize = float(paragraph_size.get(w("val"), psize * 2)) / 2
        spacing_values = {}
        maximum_size = 0
        runs = [
            run
            for run in paragraph.iter(w("r"))
            if next(run.iterancestors(w("p")), None) is paragraph
        ]
        for run in runs:
            ref = json.loads(run.get(ITEM)) if run.get(ITEM) else None
            explicit = item_style(options, ref["key"], ref["kind"]) if ref else {}
            for name in ("space_before", "space_after", "line_spacing"):
                if name in explicit:
                    spacing_values[name] = max(spacing_values.get(name, 0), explicit[name])
            size = explicit.get("font_size")
            if options.auto_fit and run.findall(w("t")):
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
                size = min(actual, max(9, actual - options.auto_fit.font_delta))
                maximum_size = max(maximum_size, size)
            if size is not None:
                for name in ("sz", "szCs"):
                    child(child(run, "rPr"), name).set(w("val"), str(round(size * 2)))
        if spacing_values or options.auto_fit and any(run.findall(w("t")) for run in runs):
            spacing = child(child(paragraph, "pPr"), "spacing")
            original = dict(default_spacing.attrib) if default_spacing is not None else {}
            original.update(style_properties(definitions, identifier, "w:pPr/w:spacing"))
            original.update(spacing.attrib)
            for prop, attr in (("space_before", "before"), ("space_after", "after")):
                amount = spacing_values.get(prop)
                if amount is not None or options.auto_fit:
                    amount = (
                        amount if amount is not None else float(original.get(w(attr), "0")) / 20
                    )
                    if options.auto_fit:
                        amount *= options.auto_fit.spacing_factor
                    spacing.set(w(attr), str(round(amount * 20)))
                    spacing.attrib.pop(w(attr + "Autospacing"), None)
                    spacing.attrib.pop(w(attr + "Lines"), None)
            line = spacing_values.get("line_spacing")
            if line is not None:
                original[w("lineRule")] = "auto"
            if options.auto_fit:
                rule = original.get(w("lineRule"), "auto")
                if line is None and rule == "auto":
                    line = float(original.get(w("line"), "240")) / 240
                if line is not None:
                    line = min(line, 1 + (line - 1) * options.auto_fit.spacing_factor)
                elif rule in {"exact", "atLeast"} and w("line") in original:
                    # 固定行距保留最大字号的 1.2 倍行框，本来更小的人工行距不放大
                    original_line = float(original[w("line")])
                    tightened = min(
                        original_line,
                        max(maximum_size * 24, original_line * options.auto_fit.spacing_factor),
                    )
                    spacing.set(w("line"), str(round(tightened)))
                    spacing.set(w("lineRule"), rule)
            if line is not None:
                spacing.set(w("line"), str(round(line * 240)))
                spacing.set(w("lineRule"), "auto")
    fit_textboxes(root, options)
    for node in root.iter():
        node.attrib.pop(ITEM, None)
        node.attrib.pop(BREAK, None)
