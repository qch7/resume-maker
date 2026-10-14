"""冻结非页码 Word 域指令，保留显示结果、样式，使复杂字段可直接填写"""

import re
from dataclasses import dataclass, field

from resume_maker.integrations.word.ooxml import w

STORIES = {w(tag) for tag in ("txbxContent", "footnote", "endnote")}
FIELD_CONTENT = (w("fldChar"), w("instrText"), w("t"))


def field_kind(code: str) -> str:
    """仅从域指令中提取域名"""
    match = re.match(r"\s*([A-Za-z]+)\b", code)
    return match[1].upper() if match else "未知域"


@dataclass
class ComplexField:
    """记录跨文字片段的完整域，保留指令、显示结果的明确边界"""

    codes: list = field(default_factory=list)
    controls: list = field(default_factory=list)
    separated: bool = False
    complete: bool = False
    has_result: bool = False
    invalid: bool = False

    @property
    def kind(self) -> str:
        """拼接被 Word 拆成多个文字片段的域指令后读取域名"""
        return field_kind("".join(node.text or "" for node in self.codes))


def complex_fields(root) -> list[ComplexField]:
    """按正文、文本框及独立脚注分别匹配域边界以免跨故事或嵌套指令被误删"""
    stacks, fields = {}, []
    for node in root.iter(*FIELD_CONTENT):
        story = next((parent for parent in node.iterancestors() if parent.tag in STORIES), root)
        stack = stacks.setdefault(story, [])
        if node.tag == w("fldChar"):
            kind = node.get(w("fldCharType"))
            if kind == "begin":
                if stack and not stack[-1].separated:
                    stack[-1].invalid = True
                current = ComplexField(controls=[node])
                stack.append(current)
                fields.append(current)
            elif stack and kind == "separate":
                current = stack[-1]
                current.invalid |= current.separated
                current.separated = True
                current.controls.append(node)
            elif stack and kind == "end":
                current = stack.pop()
                current.controls.append(node)
                current.complete = True
        elif node.tag == w("instrText"):
            if stack and not stack[-1].separated:
                stack[-1].codes.append(node)
            else:
                fields.append(ComplexField(codes=[node], invalid=True))
        elif node.tag == w("t") and (node.text or "").strip():
            for current in stack:
                if current.separated:
                    current.has_result = True
    return fields


def freeze_fields(root) -> list[str]:
    """冻结非页码域、不完整域，保留显示结果，无缓存处作为可填空位"""
    kinds, retained = [], set()
    for current in complex_fields(root):
        if current.kind in {"PAGE", "NUMPAGES"} and current.complete and not current.invalid:
            retained.update([*current.codes, *current.controls])
        else:
            kinds.append(current.kind)
    for node in list(root.iter(w("instrText"), w("fldChar"))):
        if node not in retained:
            node.getparent().remove(node)
            if not kinds:
                kinds.append("不完整的域")
    for node in list(root.iter(w("fldSimple"))):
        kind = field_kind(node.get(w("instr"), ""))
        if kind in {"PAGE", "NUMPAGES"}:
            continue
        parent, position = node.getparent(), node.getparent().index(node)
        for child in list(node):
            if child.tag != w("fldData"):
                parent.insert(position, child)
                position += 1
        parent.remove(node)
        kinds.append(kind)
    return list(dict.fromkeys(kinds))


def unsupported_fields(root) -> list[str]:
    """列出待处理域，保留页码、总页数，拒绝放行未知或不完整域"""
    kinds = [field_kind(node.get(w("instr"), "")) for node in root.iter(w("fldSimple"))]
    kinds.extend(
        current.kind if current.complete and not current.invalid else "不完整的域"
        for current in complex_fields(root)
    )
    return list(dict.fromkeys(kind for kind in kinds if kind not in {"PAGE", "NUMPAGES"}))
