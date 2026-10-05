"""荣誉来源字段的稳定标识和默认标签"""

HONOR_CUSTOM_FIELDS = {
    "award": "奖项",
    "level": "荣誉级别",
    "recipient": "获奖人",
    "certificate_number": "证书编号",
    "category": "分类",
}
HONOR_CUSTOM_IDS = {f"honor-field:{key}" for key in HONOR_CUSTOM_FIELDS}
