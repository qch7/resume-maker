"""拆分误合并的电话、邮箱引文，避免把同排联系方式补到新行"""

import re

from lxml import etree

from resume_maker.domain.templates import TextBinding
from resume_maker.integrations.word.ooxml import w
from resume_maker.integrations.word.templates.contact_style import SLOT_VERSION
from resume_maker.integrations.word.templates.mapping import paragraph_text, quote_range
from resume_maker.integrations.word.templates.supplement import remap_plan

LABELS = re.compile(
    r"(?P<phone>联系电话|电话|手机|Telephone|Phone|Mobile|Tel)\s*[:：]\s*"
    r"|(?P<email>电子邮箱|邮箱|E-?mail)\s*[:：]\s*",
    re.IGNORECASE,
)


def combined_contacts(paragraph, binding):
    """仅拆分有明确双标签、格式可核验且完整位于原引文内的电话及邮箱"""
    text = paragraph_text(paragraph)
    labels = list(LABELS.finditer(text))
    if len(labels) != 2 or {item.lastgroup for item in labels} != {"phone", "email"}:
        return None
    start, end = quote_range(text, binding)
    values = []
    for index, label in enumerate(labels):
        stop = labels[index + 1].start() if index + 1 < len(labels) else len(text)
        value = text[label.end() : stop].strip(" \t\r\n|｜;；·")
        offset = text.find(value, label.end(), stop)
        pattern = (
            r"[+\d][\d ()+.\-]{5,30}"
            if label.lastgroup == "phone"
            else r"[^\s@：:|｜]+@[^\s@：:|｜]+\.[A-Za-z]{2,}"
        )
        if not re.fullmatch(pattern, value) or offset < start or offset + len(value) > end:
            return None
        values.append(
            TextBinding(
                node=binding.node,
                quote=value,
                target=f"personal.{label.lastgroup}",
                occurrence=1 + len(list(re.finditer(re.escape(value), text[:offset]))),
            )
        )
    return values


def separate_contact_bindings(package, plan):
    """在独立副本修正合并引文，仅移除同字段由程序生成的独占补位段落"""
    for binding in plan.fields:
        if binding.target not in {"personal.phone", "personal.email"}:
            continue
        replacements = combined_contacts(package.node(binding.node), binding)
        if replacements is None:
            continue
        others = [
            field
            for field in plan.fields
            if field is not binding and field.target in {item.target for item in replacements}
        ]
        if any(
            package.node(field.node).get(SLOT_VERSION) != "1"
            or sum(other.node == field.node for other in plan.fields) != 1
            or field.node in [*plan.keep, *plan.remove]
            or any(
                field.node in (region.start, region.end, region.sample_start, region.sample_end)
                for region in plan.repeats
            )
            for field in others
        ):
            continue
        working, updated = package.clone(), plan.model_copy(deep=True)
        previous = dict(working.nodes)
        obsolete = {field.node for field in others}
        updated.fields = [
            field for field in updated.fields if field.node not in obsolete and field != binding
        ]
        for identifier in obsolete:
            node = working.node(identifier)
            parent = node.getparent()
            parent.remove(node)
            if parent.tag == w("tc") and not parent.findall(w("p")):
                parent.append(etree.Element(w("p")))
        working.reindex()
        updated = remap_plan(updated, previous, working)
        updated.fields.extend(
            field.model_copy(update={"node": working.ids[previous[field.node]]})
            for field in replacements
        )
        if not working.review(updated)["ready"]:
            continue
        notice = "已拆分同一行的电话、邮箱填写位置，保留原有分隔及文字样式。"
        working.notices = [*package.notices, notice]
        return working, updated, [notice]
    return package, plan, []
