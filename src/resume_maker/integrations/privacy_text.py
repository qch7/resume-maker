"""将 OCR 字宽、间隔归一化后定位原文，替换仍保留原始引文"""

import re
import unicodedata
from array import array
from io import StringIO
from itertools import repeat


def normalized_text(value, *, compact=False):
    """为归一化字符记录原文位置，删除格式控制符并按需忽略空白"""
    if value.isascii():
        view = value, range(len(value))
    else:
        text, positions = StringIO(), array("I" if len(value) <= 0xFFFFFFFF else "Q")
        for index, character in enumerate(value):
            if unicodedata.category(character) == "Cf":
                continue
            # 保持逐字符归一化，不能让相邻组合字符跨原文位置合成
            normalized = unicodedata.normalize("NFKC", character)
            text.write(normalized)
            positions.extend(repeat(index, len(normalized)))
        view = text.getvalue(), positions
    return compact_text(view) if compact else view


def compact_text(view):
    """从普通视图去除空白，沿用展开字符、格式符对应的原文坐标"""
    text, original = view
    if not re.search(r"\s", text):
        return view
    parts = StringIO()
    positions = array("I" if not original or original[-1] <= 0xFFFFFFFF else "Q")
    for match in re.finditer(r"\S+", text):
        parts.write(match[0])
        positions.extend(original[match.start() : match.end()])
    return parts.getvalue(), positions


def known_pattern(known):
    """只在敏感词代次改变时准备 OCR 变体匹配器"""
    candidates = {
        normalized_text(candidate, compact=True)[0]
        for candidate in known
        if isinstance(candidate, str) and candidate
    }
    candidates = {candidate for candidate in candidates if len(candidate) >= 2}
    if not candidates:
        return None
    return re.compile("|".join(re.escape(v) for v in sorted(candidates, key=len, reverse=True)))


def known_variants(value, pattern, *, normalized=None):
    """用本轮词表定位 OCR 变体，返回可准确还原的原始片段"""
    if pattern is None:
        return set()
    text, positions = (
        normalized_text(value, compact=True) if normalized is None else compact_text(normalized)
    )
    return {
        value[positions[match.start()] : positions[match.end() - 1] + 1]
        for match in pattern.finditer(text)
    }


def labeled_values(value, pattern, *, normalized=None):
    """在统一字宽后的标签中发现身份，并返回原文值用于后续替换"""
    text, positions = normalized_text(value) if normalized is None else normalized
    return {
        value[positions[match.start(1)] : positions[match.end(1) - 1] + 1].strip().strip("\"'")
        for match in pattern.finditer(text)
        if match.end(1) > match.start(1)
    }


def formatted_values(value, patterns, *, normalized=None):
    """对未登记的联系方式也按统一字宽匹配，避免 OCR 全角字符绕过规则"""
    text, positions = normalized_text(value) if normalized is None else normalized
    return {
        value[positions[match.start()] : positions[match.end() - 1] + 1]
        for pattern in patterns
        for match in pattern.finditer(text)
    }


def literal_spans(value, *patterns):
    """合并独立匹配器，保持最早起点、同起点最长值及后续重新查找的语义"""
    patterns = [pattern for pattern in patterns if pattern is not None]
    if len(patterns) == 1:
        yield from (match.span() for match in patterns[0].finditer(value))
        return
    matches = [pattern.search(value) for pattern in patterns]
    while any(match is not None for match in matches):
        selected = min(
            (match for match in matches if match is not None),
            key=lambda match: (match.start(), -match.end()),
        )
        yield selected.span()
        for index, match in enumerate(matches):
            # 被另一匹配覆盖的候选须从新边界重查，不能跳过内部的下一条合法命中
            if match is not None and match.start() < selected.end():
                matches[index] = patterns[index].search(value, selected.end())
