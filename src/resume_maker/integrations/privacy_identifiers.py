"""识别完整编号及 OCR 分组，返回原文范围以保留精确还原能力"""

import re

from resume_maker.integrations.privacy_text import normalized_text

IDENTIFIER_KEYS = {
    "student_id",
    "student_number",
    "admission_number",
    "exam_number",
    "report_number",
    "report_id",
    "certificate_id",
    "document_number",
    "verification_code",
    "validation_code",
    "准考证号",
    "准考证号码",
    "报告单编号",
    "报告单号码",
    "成绩单编号",
    "证件号码",
    "报名号",
    "学籍号",
    "学生编号",
    "验证码",
    "校验码",
    "验证代码",
    "印章编号",
}
LABELS = IDENTIFIER_KEYS | {
    "student ID",
    "admission number",
    "report number",
    "certificate number",
    "document number",
    "verification code",
    "证书编号",
    "学号",
    "身份证号",
    "身份证号码",
}
LABEL_PATTERN = "|".join(
    r"[ \t]*".join(re.escape(character) for character in label)
    for label in sorted(LABELS, key=len, reverse=True)
)
LABELED = re.compile(
    rf"(?:{LABEL_PATTERN})(?:[ \t]*[:=#][ \t]*|\s+)"
    r"([a-z0-9](?:[a-z0-9 _/-]{0,118}[a-z0-9])?)",
    re.I,
)
LONG_NUMBER = re.compile(r"(?<!\d)(?<!\d\.)\d{12,}[Xx]?(?!\d|\.\d)")
GROUPED = re.compile(r"(?<!\d)(?<!\d\.)\d{2,}(?:[ \t/-]+\d{2,})+(?!\d|\.\d)")
WRAPPED = re.compile(r"(?<!\d)(?<!\d\.)\d{5,}(?:[ \t]*[\r\n]+[ \t]*\d{5,})+(?!\d|\.\d)")
VERIFICATION = re.compile(r"(?<![a-z0-9])[a-z0-9]{4}(?:[ \t-]+[a-z0-9]{4}){3,7}(?![a-z0-9])", re.I)


def identifier_spans(value):
    """覆盖长数字、明确标签和分组校验串，避免把独立成绩及日期拼成编号"""
    text, positions = normalized_text(value)
    spans = []
    for pattern in (LONG_NUMBER, GROUPED, WRAPPED, VERIFICATION, LABELED):
        for match in pattern.finditer(text):
            group = 1 if pattern is LABELED else 0
            candidate = match[group]
            numbers = re.findall(r"\d+", candidate)
            if pattern in (GROUPED, WRAPPED):
                if sum(map(len, numbers)) < 12:
                    continue
                if max(map(len, numbers)) < 5 and not all(len(part) == 4 for part in numbers):
                    continue
                if all(len(part) == 4 and 1900 <= int(part) <= 2099 for part in numbers):
                    continue
            if pattern in (LABELED, VERIFICATION) and not numbers:
                continue
            if pattern is VERIFICATION and not re.search(r"[a-z]", candidate, re.I):
                continue
            spans.append((positions[match.start(group)], positions[match.end(group) - 1] + 1))
    return spans


def identifier_values(value):
    """登记完整编号及已确定的分块，防止正文遮盖后 OCR 小块仍泄漏"""
    values = set()
    for start, end in identifier_spans(value):
        original = value[start:end]
        values.add(original)
        normalized, positions = normalized_text(original)
        for match in re.finditer(r"[a-z0-9]{4,}", normalized, re.I):
            values.add(original[positions[match.start()] : positions[match.end() - 1] + 1])
    return values


def literal_pattern(value):
    """短数字敏感词只匹配独立值，不替换日期、分数或变量中的局部数字"""
    normalized, _ = normalized_text(value, compact=True)
    escaped = re.escape(value)
    if normalized.isdecimal() and len(normalized) < 12:
        return rf"(?<![\dA-Za-z_.]){escaped}(?![\dA-Za-z_.])"
    return escaped
