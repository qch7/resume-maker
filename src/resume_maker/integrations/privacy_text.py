"""将 OCR 字宽和间隔归一化后定位原文，替换仍保留原始引文"""

import re
import unicodedata


def normalized_text(value, *, compact=False):
    """为归一化字符记录原文位置，删除格式控制符并按需忽略空白"""
    text, positions = [], []
    for index, character in enumerate(value):
        if unicodedata.category(character) == "Cf":
            continue
        for normalized in unicodedata.normalize("NFKC", character):
            if compact and normalized.isspace():
                continue
            text.append(normalized)
            positions.append(index)
    return "".join(text), positions


def known_variants(value, known):
    """定位已登记身份的 OCR 空白和字宽变体，返回可准确还原的原始片段"""
    candidates = {
        normalized_text(candidate, compact=True)[0]
        for candidate in known
        if isinstance(candidate, str) and candidate
    }
    candidates = {candidate for candidate in candidates if len(candidate) >= 2}
    if not candidates:
        return set()
    text, positions = normalized_text(value, compact=True)
    pattern = re.compile("|".join(re.escape(v) for v in sorted(candidates, key=len, reverse=True)))
    return {
        value[positions[match.start()] : positions[match.end() - 1] + 1]
        for match in pattern.finditer(text)
    }


def labeled_values(value, pattern):
    """在统一字宽后的标签中发现身份，并返回原文值用于后续替换"""
    text, positions = normalized_text(value)
    return {
        value[positions[match.start(1)] : positions[match.end(1) - 1] + 1].strip().strip("\"'")
        for match in pattern.finditer(text)
        if match.end(1) > match.start(1)
    }


def formatted_values(value, patterns):
    """对未登记的联系方式也按统一字宽匹配，避免 OCR 全角字符绕过规则"""
    text, positions = normalized_text(value)
    return {
        value[positions[match.start()] : positions[match.end() - 1] + 1]
        for pattern in patterns
        for match in pattern.finditer(text)
    }
