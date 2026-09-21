"""根据项目字段含义安排空位并保留模板已有的字段位置"""

from copy import deepcopy

from lxml import etree

from resume_maker.core.errors import Problem
from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.templates.flow import effective_section
from resume_maker.integrations.word.templates.mapping import (
    paragraph_text,
    paragraph_texts,
    quote_range,
)

METADATA = {"period": "参与时间", "role": "担任角色", "stack": "技术栈"}
ORDER = {
    target: index
    for index, target in enumerate(
        (
            "title",
            "period",
            "role",
            "stack",
            "description",
            "custom_fields",
            "details",
            "highlights",
        )
    )
}
PLACEHOLDER = "〔待填写〕"


def explicit_slot(node, nodes, keep):
    """保留带标签、图标或固定装饰的字段空位"""
    if node.xpath("w:pPr/w:framePr | w:pPr/w:pBdr | w:pPr/w:shd | w:pPr/w:numPr", namespaces=NS):
        return True
    previous = node.getprevious()
    if previous is None:
        return False
    if previous.xpath(".//w:drawing | .//w:pict", namespaces=NS):
        return True
    return previous in [nodes[identifier] for identifier in keep if identifier in nodes] and bool(
        paragraph_text(previous).strip()
    )


def run_style(paragraph, offset):
    """按引文字符位置继承真实文字运行样式，区分标签和值的字重及字体"""
    position = 0
    for text in paragraph_texts(paragraph):
        position += len(text.text or "")
        if position > offset:
            run = next(text.iterancestors(w("r")), None)
            style = run.find(w("rPr")) if run is not None else None
            return deepcopy(style) if style is not None else None
    return None


def labelled_slot(donor, binding, label):
    """只继承相邻正文的缩进、行距和字体来创建带标签段落"""
    paragraph = etree.Element(w("p"))
    properties = donor.find(w("pPr"))
    properties = deepcopy(properties) if properties is not None else etree.Element(w("pPr"))
    for node in list(properties):
        if node.tag in {w("sectPr"), w("framePr"), w("numPr"), w("tabs"), w("pageBreakBefore")}:
            properties.remove(node)
    paragraph.append(properties)
    start, _ = quote_range(paragraph_text(donor), binding)
    for value, offset in ((label + "：", 0), (PLACEHOLDER, start)):
        run = etree.SubElement(paragraph, w("r"))
        style = run_style(donor, offset)
        if style is not None:
            run.append(style)
        etree.SubElement(run, w("t")).text = value
    return paragraph


def prepare_project_slots(nodes, fields, values, keep):
    """只规范项目样本内无标签的空白元信息位置，返回本条克隆的映射和可清理空段落"""
    if "_highlight_items" not in values:
        return fields, []
    updated, empty = list(fields), []
    for field in sorted(fields, key=lambda field: ORDER.get(field.target, len(ORDER))):
        if field.quote or field.target not in METADATA:
            continue
        slot = nodes[field.node]
        if explicit_slot(slot, nodes, keep):
            continue
        candidates = [
            other
            for other in updated
            if other.quote
            and other.target in ORDER
            and nodes[other.node].getparent() is slot.getparent()
            and not nodes[other.node].xpath(
                "w:pPr/w:framePr | .//w:drawing | .//w:pict", namespaces=NS
            )
        ]
        if not candidates:
            continue
        if not values.get(field.target):
            updated.remove(field)
            empty.append(slot)
            continue
        candidates = [
            other
            for other in candidates
            if effective_section(slot) is effective_section(nodes[other.node])
        ]
        if not candidates:
            raise Problem(
                f"未标注的“{METADATA[field.target]}”空位跨越分节，无法可靠安排到项目基本信息区，请调整该字段映射。"
            )
        # 补位后根据当前段落顺序确定插入位置
        order = {node: index for index, node in enumerate(slot.getparent())}
        later = [other for other in candidates if ORDER[other.target] > ORDER[field.target]]
        anchor = (
            min(later, key=lambda other: order[nodes[other.node]])
            if later
            else max(candidates, key=lambda other: order[nodes[other.node]])
        )
        donor = nodes[anchor.node]
        paragraph = labelled_slot(donor, anchor, METADATA[field.target])
        if later:
            donor.addprevious(paragraph)
        else:
            donor.addnext(paragraph)
            section = donor.find("w:pPr/w:sectPr", NS)
            if section is not None:
                # 将节结束标记移到新元信息之后以保留其所属节
                paragraph.find(w("pPr")).append(section)
        nodes[field.node] = paragraph
        updated[updated.index(field)] = field.model_copy(update={"quote": PLACEHOLDER})
        empty.append(slot)
    return updated, empty
