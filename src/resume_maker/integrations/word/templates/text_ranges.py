"""在单段落内索引文字位置，按倒序替换保留原有运行样式"""

from bisect import bisect_left, bisect_right
from copy import deepcopy
from dataclasses import dataclass
from itertools import pairwise

from lxml import etree

from resume_maker.integrations.word.item_layout import mark_run
from resume_maker.integrations.word.ooxml import w

TEXT = w("t")
CONTROLS = (w("br"), w("cr"), w("tab"))


@dataclass
class StyledText:
    """为同一引文中的多条内容分别携带标题、正文样式"""

    pieces: list


def set_styled_text(node, prefix, value, suffix):
    """仅拆分命中的文字运行，前后文字、控制节点继续保留原样式"""
    run = node.getparent()
    parent, position = run.getparent(), run.getparent().index(run) + 1
    following = list(run)[run.index(node) + 1 :]
    original_style = run.find(w("rPr"))
    for child in following:
        run.remove(child)
    run.remove(node)
    first = None
    if prefix:
        first = set_text(etree.SubElement(run, TEXT), prefix)
    for piece in value.pieces:
        text, style, *metadata = piece
        added = etree.Element(w("r"))
        if style is not None:
            added.append(deepcopy(style))
        start = set_text(etree.SubElement(added, TEXT), text)
        if metadata:
            mark_run(added, metadata[0], boundary=bool(metadata[1]) if len(metadata) > 1 else False)
        first = first if first is not None else start
        parent.insert(position, added)
        position += 1
    if suffix or following:
        tail = etree.Element(w("r"))
        if original_style is not None:
            tail.append(deepcopy(original_style))
        if suffix:
            set_text(etree.SubElement(tail, TEXT), suffix)
        tail.extend(following)
        parent.insert(position, tail)
    return first


def set_text(node, value):
    """把用户换行转为 Word 节点，返回仍可承接左侧替换的首段文字"""
    parent, index = node.getparent(), node.getparent().index(node)
    parent.remove(node)
    first = None
    for offset, line in enumerate(value.split("\n")):
        if offset:
            parent.insert(index, etree.Element(w("br")))
            index += 1
        text = etree.Element(TEXT)
        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text.text = line
        parent.insert(index, text)
        index += 1
        if first is None:
            first = text
    return first


class ParagraphTextIndex:
    """只记录本段文字及控制字符，文本框内的独立段落保持隔离"""

    def __init__(self, paragraph):
        """一次遍历建立文本区间及不占文字偏移的控制节点位置"""
        self.paragraph = paragraph
        self.texts, self.starts, self.ends = [], [], []
        self.controls, self.control_positions = [], []
        parts, position = [], 0
        for node in paragraph.iter(TEXT, *CONTROLS):
            if next(node.iterancestors(w("p")), None) is not paragraph:
                continue
            if node.tag == TEXT:
                text = node.text or ""
                self.texts.append(node)
                self.starts.append(position)
                position += len(text)
                self.ends.append(position)
                parts.append(text)
            else:
                self.controls.append(node)
                self.control_positions.append(position)
        self.text = "".join(parts)
        self.boundaries = set(self.control_positions)

    def replace(self, start, end, value, modified_links):
        """按原始偏移修改命中的运行，右侧变更只更新可继续编辑的首段指针"""
        if start == end == 0:
            run = next(iter(self.paragraph.findall(w("r"))), None)
            if run is None:
                run = etree.SubElement(self.paragraph, w("r"))
            node = etree.SubElement(run, TEXT)
            if isinstance(value, StyledText):
                set_styled_text(node, "", value, "")
            else:
                set_text(node, value)
            return
        # 引文端点上的换行、制表符保留，只移除严格位于内部的旧控制节点
        left = bisect_right(self.control_positions, start)
        right = bisect_left(self.control_positions, end)
        for node in self.controls[left:right]:
            node.getparent().remove(node)
        left = bisect_right(self.ends, start)
        right = bisect_left(self.starts, end)
        preferred = left
        for index in range(left, right):
            text, position = self.texts[index], self.starts[index]
            if (text.text or "")[max(0, start - position) : end - position].strip():
                preferred = index
                break
        for index in range(left, right):
            text, position = self.texts[index], self.starts[index]
            link = next(text.iterancestors(w("hyperlink")), None)
            if link is not None:
                modified_links.add(link)
            original = text.text or ""
            prefix = original[: max(0, start - position)]
            suffix = original[max(0, end - position) :]
            if index == preferred and isinstance(value, StyledText):
                self.texts[index] = set_styled_text(text, prefix, value, suffix)
            else:
                self.texts[index] = set_text(
                    text, prefix + (value if index == preferred else "") + suffix
                )

    def apply(self, replacements):
        """非重叠范围共用索引，扩展后的重叠或空范围沿用逐次重读的倒序语义"""
        ordered = sorted(replacements, reverse=True)
        reusable = all(start < end for start, end, _ in ordered) and all(
            left[1] <= right[0] for right, left in pairwise(ordered)
        )
        modified_links = set()
        for start, end, value in ordered:
            current = self if reusable else ParagraphTextIndex(self.paragraph)
            current.replace(start, end, value, modified_links)
        for link in modified_links:
            if next(link.iterancestors(w("p")), None) is not self.paragraph:
                continue
            parent = link.getparent()
            for child in list(link):
                parent.insert(parent.index(link), child)
            parent.remove(link)
