"""系统日志采集类别的持久化契约"""

import re
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

ActivityCategory = Literal["api", "ai", "tool", "task", "service", "system", "client"]
ACTIVITY_CATEGORIES = get_args(ActivityCategory)


def normalize_hidden_rules(value: str) -> str:
    """限制隐藏规则的长度、数量和语法，按顺序去重"""
    if len(value) > 4000:
        raise ValueError("规则总长度不能超过 4,000 字符")
    lines = list(dict.fromkeys(line.strip() for line in value.splitlines() if line.strip()))
    if len(lines) > 100:
        raise ValueError("最多填写 100 条隐藏规则")
    for line in lines:
        if not re.fullmatch(
            r"(?:(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) )?/api/[^\s?#]*|"
            r"(?:ai|task|system|client):[A-Za-z0-9_.*-]+|"
            r"[A-Za-z_*][A-Za-z0-9_.*-]*\.[A-Za-z0-9_.*-]+",
            line,
        ):
            raise ValueError("隐藏规则须为 API 路径、操作名或类型:事件，支持方法前缀和星号")
    return "\n".join(lines)


class ActivityRuleDefaults(BaseModel):
    """向页面发布当前日志实例使用的默认隐藏规则"""

    hidden_rules: list[str] = Field(max_length=100)


class ActivityCaptureSettings(BaseModel):
    """只允许已知类别，空列表表示暂停全部日志采集"""

    model_config = ConfigDict(extra="forbid")
    categories: list[ActivityCategory] = Field(max_length=len(ACTIVITY_CATEGORIES))

    @field_validator("categories")
    @classmethod
    def normalize_categories(cls, value):
        """按固定顺序去重，保存和读取使用相同类别顺序"""
        return [category for category in ACTIVITY_CATEGORIES if category in value]
