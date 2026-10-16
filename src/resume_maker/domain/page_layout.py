"""每份简历独立保存的版面预算及有界排版选项"""

from pydantic import Field

from resume_maker.domain.models import Model

LAYOUT_KEY = "sys.resume.layout"


class ResumeLayout(Model):
    """缺省沿用原模板，只对明确选择的正文、段落参数作调整"""

    target_pages: int = Field(default=1, ge=1, le=3)
    font_size: float | None = Field(default=None, ge=9, le=12)
    space_after: float | None = Field(default=None, ge=0, le=8)
    line_spacing: float | None = Field(default=None, ge=1, le=1.5)
    honors_inline: bool = False


def layout_options(extensions):
    """读取独立命名空间，未知扩展及未设置的方案保持原样"""
    value = extensions.get(LAYOUT_KEY, {})
    if not isinstance(value, dict):
        raise ValueError("版面设置格式无效。")
    return ResumeLayout.model_validate(value.get("options", {}))
