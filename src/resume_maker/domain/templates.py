"""陌生 Word 模板的声明式映射；模型只选择节点和字段，不生成执行代码。"""

from pydantic import Field

from resume_maker.domain.models import Model


class TextBinding(Model):
    """以精确引文定位段落中的值，可跨多个 Word 文本片段。"""

    node: str
    quote: str = Field(max_length=10000)
    target: str
    occurrence: int = Field(default=1, ge=1, le=100)


class RepeatBinding(Model):
    """以一个条目为样式样本，替换同级节点范围内的全部示例条目。"""

    section: str
    start: str
    end: str
    sample_start: str
    sample_end: str
    fields: list[TextBinding] = Field(min_length=1, max_length=100)


class TemplatePlan(Model):
    """待用户核对的字段、重复区、照片、固定文字和删除项。"""

    summary: str = Field(max_length=2000)
    fields: list[TextBinding] = Field(max_length=150)
    repeats: list[RepeatBinding] = Field(max_length=40)
    photos: list[str] = Field(max_length=10)
    keep: list[str] = Field(max_length=2000)
    remove: list[str] = Field(max_length=2000)
    warnings: list[str] = Field(max_length=30)
