"""按当前简历编排项目正文；在输出副本中保留标题时间及各字段的文字样式"""

import re
from copy import deepcopy

from lxml import etree

from resume_maker.core.errors import Problem
from resume_maker.integrations.word.ooxml import w
from resume_maker.integrations.word.templates.entry_layout import apply_indent, common_indent
from resume_maker.integrations.word.templates.layout import CONTAINERS, child_in
from resume_maker.integrations.word.templates.mapping import paragraph_text, quote_range
from resume_maker.integrations.word.templates.project_slots import run_style
from resume_maker.integrations.word.templates.sections import entry_blocks

BODY_TARGETS = {
    "role",
    "subtitle",
    "stack",
    "description",
    "details",
    "custom_fields",
    "highlights",
}
LABELS = {
    "role": r"担任角色|项目角色|角色|Role",
    "subtitle": r"担任角色|项目角色|角色|Role",
    "stack": r"技术栈|Stack|Tech Stack",
    "description": r"项目描述|描述|Description",
    "details": r"项目详情|详情|Details",
    "highlights": r"项目亮点|亮点|Highlights",
    "custom_fields": r"自定义信息|Custom Fields",
}


def empty_project_range(text, fields, binding, start, end):
    """移走同段正文时一并清除其字段标签及前导分隔符；边界不触及标题和时间"""
    if binding.target not in BODY_TARGETS:
        return start, end
    preceding = [
        quote_range(text, field)[1]
        for field in fields
        if field.node == binding.node
        and field is not binding
        and quote_range(text, field)[1] <= start
    ]
    left = max(preceding, default=0)
    prefix = text[left:start]
    match = re.search(
        r"[\s|·,，;；\-–—]*(?:(?:" + LABELS[binding.target] + r")\s*[:：]?\s*)?$",
        prefix,
        re.IGNORECASE,
    )
    return (left + match.start() if match else start), end


def ordered_paragraph(entry, nodes, fields, styles):
    """沿用对应字段的段落和标签正文样式；展开自定义项及亮点；移除固定定位和分节"""
    target = "custom_fields" if entry["key"].startswith("custom:") else entry["key"]
    choices = [
        target,
        "subtitle" if target == "role" else target,
        "details",
        "description",
        "stack",
        "role",
        "title",
    ]
    binding = next(field for key in choices for field in fields if field.target == key)
    donor = nodes[binding.node]
    paragraph = etree.Element(w("p"))
    properties = donor.find(w("pPr"))
    properties = deepcopy(properties) if properties is not None else etree.Element(w("pPr"))
    for node in list(properties):
        if node.tag in {w("sectPr"), w("framePr"), w("numPr"), w("tabs"), w("pageBreakBefore")}:
            properties.remove(node)
    paragraph.append(properties)
    text = paragraph_text(donor)
    start, end = quote_range(text, binding)
    # 亮点或综合正文引文往往包含粗体标签；正文应继承冒号后实际正文的字重
    colon = re.search(r"[:：]", text[start:end])
    body_start = start + colon.end() if colon and colon.start() < 50 else start
    while body_start < end and text[body_start].isspace():
        body_start += 1
    label_start = 0 if text[:start].strip() else start
    for value, offset in ((entry["label"] + "：", label_start), (entry["text"], body_start)):
        style = run_style(donor, offset)
        for index, line in enumerate(value.split("\n")):
            run = etree.SubElement(paragraph, w("r"))
            if style is not None:
                run.append(deepcopy(style))
            if index:
                etree.SubElement(run, w("br"))
            node = etree.SubElement(run, w("t"))
            node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            node.text = line
    indent = common_indent(styles, nodes, fields)
    styles.isolate_indent(paragraph, indent)
    apply_indent(paragraph, indent, unnumbered=True)
    return paragraph


def arrange_project_body(nodes, fields, record, styles):
    """显式编排时将正文按行输出在标题时间之后；未编排项目完全沿用模板原布局"""
    if not record.get("_body_ordered"):
        return record, []
    paragraphs = [nodes[field.node] for field in fields]
    parent = next(
        (
            ancestor
            for ancestor in paragraphs[0].iterancestors()
            if ancestor.tag in CONTAINERS
            and all(ancestor in node.iterancestors() for node in paragraphs)
        ),
        None,
    )
    if parent is None:
        raise Problem("项目字段不在同一可编排区域，请调整模板的项目边界。")
    fixed = [nodes[field.node] for field in fields if field.target in {"title", "period"}]
    position = (
        max(parent.index(child_in(node, parent)) for node in fixed) + 1
        if fixed
        else min(parent.index(child_in(node, parent)) for node in paragraphs)
    )
    body = [ordered_paragraph(entry, nodes, fields, styles) for entry in record["_body_entries"]]
    if body:
        for block in entry_blocks(parent, body):
            parent.insert(position, block)
            position += 1
    blank_labels = []
    for field in fields:
        if field.target not in BODY_TARGETS:
            continue
        previous = nodes[field.node].getprevious()
        if (
            previous is not None
            and previous not in paragraphs
            and re.fullmatch(
                r"\s*(?:" + LABELS[field.target] + r")\s*[:：]?\s*",
                paragraph_text(previous),
                re.IGNORECASE,
            )
            and not previous.xpath(
                ".//*[local-name()='drawing' or local-name()='pict' or local-name()='object']"
            )
        ):
            blank_labels.append(previous)
    return {**record, **dict.fromkeys(BODY_TARGETS, ""), "_highlight_items": []}, blank_labels
