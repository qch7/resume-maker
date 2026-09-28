"""系统日志采集类别的持久化契约"""

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

ActivityCategory = Literal["api", "ai", "tool", "task", "service", "system", "client"]
ACTIVITY_CATEGORIES = get_args(ActivityCategory)


class ActivityCaptureSettings(BaseModel):
    """只允许已知类别，空列表表示暂停全部日志采集"""

    model_config = ConfigDict(extra="forbid")
    categories: list[ActivityCategory] = Field(max_length=len(ACTIVITY_CATEGORIES))

    @field_validator("categories")
    @classmethod
    def normalize_categories(cls, value):
        """按固定顺序去重，保存和读取使用相同类别顺序"""
        return [category for category in ACTIVITY_CATEGORIES if category in value]
