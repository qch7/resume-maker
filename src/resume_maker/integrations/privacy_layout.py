"""页面文字保护的纯文本规则，独立于图像解码依赖"""

import re

MAX_IMAGES = 24

SECTION_HEADING = re.compile(
    r"^(?:个人简介|自我评价|专业技能|职业技能|技能特长|工作经[历验]|实习经[历验]|"
    r"项目经[历验]|教育(?:经历|背景)|获奖(?:经历|荣誉)|荣誉奖项|"
    r"profile|summary|skills|experience|work experience|education|projects|awards)$",
    re.IGNORECASE,
)


def header_values(blocks):
    """页首身份区整体保护，避免未登记姓名和 OCR 误认的联系方式漏过格式规则"""
    boundary = min(
        (row["box"][1] for row in blocks if SECTION_HEADING.fullmatch(row["text"].strip())),
        default=0.25,
    )
    return {row["text"] for row in blocks if row["box"][1] < min(boundary, 0.25)}
