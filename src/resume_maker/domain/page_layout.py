"""每份简历独立保存的版面预算及有界排版选项"""

import json

from pydantic import ConfigDict, Field

from resume_maker.domain.models import Model

LAYOUT_KEY = "sys.resume.layout"


class ItemStyle(Model):
    """只保存明确覆盖的文字及段落参数，空值继续继承模板"""

    font_size: float | None = Field(default=None, ge=6, le=72)
    space_before: float | None = Field(default=None, ge=0, le=48)
    space_after: float | None = Field(default=None, ge=0, le=48)
    line_spacing: float | None = Field(default=None, ge=0.8, le=3)


class ItemStyles(Model):
    """默认使用类型样式，存在单项记录即表示断开联动"""

    types: dict[str, ItemStyle] = Field(default_factory=dict, max_length=100)
    items: dict[str, ItemStyle] = Field(default_factory=dict, max_length=10000)


class AutoFit(Model):
    """实际样式确定后再收紧，保留各项差异及已有更小值"""

    spacing_factor: float = Field(default=1, ge=0, le=1)
    font_delta: float = Field(default=0, ge=0, le=63)


class ResumeLayout(Model):
    """缺省沿用原模板，只对明确选择的正文、段落参数作调整"""

    model_config = ConfigDict(extra="allow")

    target_pages: int = Field(default=1, ge=1, le=3)
    font_size: float | None = Field(default=None, ge=9, le=12)
    space_after: float | None = Field(default=None, ge=0, le=8)
    line_spacing: float | None = Field(default=None, ge=1, le=1.5)
    honors_inline: bool = False
    item_styles: ItemStyles = Field(default_factory=ItemStyles)
    auto_fit: AutoFit | None = None


def item_key(*parts):
    """用 JSON 元组保留分隔符、栏目身份，改名及重排不会改变样式归属"""
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


def item_kind(field, *, personal=False):
    """内置文档、模板及客户端按相同语义类型联动"""
    if personal:
        return field if field in {"name", "job_title"} else "personal"
    return {"details": "body", "description": "body", "highlights": "highlight"}.get(field, field)


def item_style(options, key, kind):
    """断链项完全替代类型声明，未覆盖属性仍交给原模板或全局处理"""
    styles = options.item_styles
    return styles.items.get(key, styles.types.get(kind, ItemStyle())).model_dump(exclude_none=True)


def layout_options(extensions):
    """读取独立命名空间，未知扩展及未设置的方案保持原样"""
    value = extensions.get(LAYOUT_KEY, {})
    if not isinstance(value, dict):
        raise ValueError("版面设置格式无效。")
    return ResumeLayout.model_validate(value.get("options", {}))
