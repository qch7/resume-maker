"""为新增联系信息选择完整条目；分别继承标签和值的文字样式"""

import re
from copy import deepcopy

from lxml import etree

from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.templates.mapping import paragraph_text
from resume_maker.integrations.word.templates.personal import personal_items

SLOT_VERSION = "{urn:resume-maker:layout}contact-slot"


def labelled_contact(paragraph, fields):
    """仅把可拆分且带明确标签的个人条目作为样式样本且不借用孤立的值或装饰"""
    parsed = personal_items(paragraph, fields)
    if parsed is None:
        return None
    for fragment, field, _ in reversed(parsed[0]):
        text = paragraph_text(fragment)
        if field.quote and re.match(r"^\s*[^:：]{1,50}[:：]", text):
            return fragment
    return None


def inherit_contact_runs(paragraph, donor, label, placeholder):
    """根据原标签和原值的运行分别复制字体、字号和字重且不继承旧链接及字符拉伸"""
    text = paragraph_text(donor) if donor is not None else ""
    match = re.match(r"^\s*[^:：]{1,50}[:：](\s*)", text)
    if match is None:
        return
    samples, position = [], 0
    for run in donor.iter(w("r")):
        if next(run.iterancestors(w("p")), None) is not donor:
            continue
        value = "".join(run.xpath(".//w:t/text()", namespaces=NS))
        if value.strip():
            samples.append((position, position + len(value), run))
        position += len(value)
    label_run = next((run for start, _, run in samples if start < match.end()), None)
    value_run = next((run for _, end, run in samples if end > match.end()), label_run)
    for run in list(paragraph.findall(w("r"))):
        paragraph.remove(run)
    for text, sample in ((label + "：", label_run), (placeholder, value_run)):
        run = etree.SubElement(paragraph, w("r"))
        properties = sample.find(w("rPr")) if sample is not None else None
        if properties is not None:
            properties = deepcopy(properties)
            # 标签里的字距、字符缩放是旧词长度的微调且不能扩散到新字段
            for node in list(properties):
                if node.tag in {w("spacing"), w("w"), w("position")}:
                    properties.remove(node)
            run.append(properties)
        node = etree.SubElement(run, w("t"))
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        node.text = text
