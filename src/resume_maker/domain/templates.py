"""陌生 Word 模板的声明式映射；模型只选择节点和字段且不生成执行代码"""

from typing import Literal

from pydantic import Field, field_validator

from resume_maker.domain.models import Model

TEMPLATE_LIBRARY_KEY = "template-library"


class TextBinding(Model):
    """以精确引文定位段落中的值；可跨多个 Word 文本片段"""

    node: str
    quote: str = Field(max_length=10000)
    target: str
    occurrence: int = Field(default=1, ge=1, le=100)


class RepeatBinding(Model):
    """以一个条目为样式样本；替换同级节点范围内的全部示例条目"""

    section: str
    start: str
    end: str
    sample_start: str
    sample_end: str
    fields: list[TextBinding] = Field(min_length=1, max_length=100)


class TemplatePlan(Model):
    """待用户核对的字段、重复区、照片、固定文字和删除项"""

    summary: str = Field(max_length=2000)
    fields: list[TextBinding] = Field(max_length=150)
    repeats: list[RepeatBinding] = Field(max_length=40)
    photos: list[str] = Field(max_length=10)
    keep: list[str] = Field(max_length=2000)
    remove: list[str] = Field(max_length=2000)
    warnings: list[str] = Field(max_length=30)


class RecoveredBlock(Model):
    """从页面识别的可编辑文字或无文字照片裁剪且只包含声明式内容"""

    text: str = Field(default="", max_length=20000)
    font_name: str = Field(default="等线", max_length=100)
    font_size: float = Field(default=11, ge=6, le=40)
    bold: bool = False
    align: Literal["left", "center", "right"] = "left"
    image_box: list[float] = Field(default_factory=list, max_length=4)

    @field_validator("image_box")
    @classmethod
    def valid_image_box(cls, box):
        """照片坐标必须完整且位于页面内；错误结果交回恢复流程自动重试"""
        if box and (len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)):
            raise ValueError("照片裁剪必须是页面内的 [左,上,右,下] 比例坐标。")
        return box


class RecoveredPage(Model):
    """一页按阅读顺序恢复的原文与照片且不根据当前简历编造源文档内容"""

    blocks: list[RecoveredBlock] = Field(max_length=1000)
    notes: list[str] = Field(default_factory=list, max_length=30)
