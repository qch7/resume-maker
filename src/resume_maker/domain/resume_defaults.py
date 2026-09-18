"""可复用的简历栏目及表单字段配置且不存储任何填写内容"""

from typing import Literal

from pydantic import Field, model_validator

from resume_maker.domain.models import DefaultField, Model

PERSONAL = set("name job_title gender age phone email gpa location website photo".split())
PROJECT = set("title period role stack description".split())
ENTRY = set("title subtitle period details".split())
HONOR = {
    f"honor-field:{key}" for key in "award level recipient certificate_number category".split()
}


def validate_fields(fields: list[DefaultField], allowed: set[str]):
    """拒绝重复标识、空白名称及超出表单容量的默认项"""
    if len({field.id for field in fields}) != len(fields):
        raise ValueError("默认项标识不能重复。")
    if sum(field.id.startswith("default:") for field in fields) > 20:
        raise ValueError("每组最多添加 20 个默认项。")
    for field in fields:
        if not field.label.strip():
            raise ValueError("默认项名称不能为空。")
        if field.id not in allowed and not (field.id.startswith("default:") and len(field.id) > 8):
            raise ValueError("默认项标识与栏目类型不匹配。")


class DefaultSection(Model):
    """新简历的栏目及其新增条目所用的字段定义"""

    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=100)
    kind: Literal["education", "projects", "text"]
    parent_id: str | None = None
    visible: bool = True
    fields: list[DefaultField] = Field(max_length=30)

    @model_validator(mode="after")
    def validate_definition(self):
        """校验栏目标题与对应表单所支持的内置字段"""
        if not self.title.strip():
            raise ValueError("栏目名称不能为空。")
        allowed = PROJECT if self.kind == "projects" else ENTRY | HONOR
        validate_fields(self.fields, allowed)
        return self


class ResumeDefaults(Model):
    """带版本的本机默认配置；保护多个窗口的并发编辑"""

    version: int = Field(default=0, ge=0)
    personal_fields: list[DefaultField] = Field(max_length=30)
    sections: list[DefaultSection] = Field(max_length=40)

    @model_validator(mode="after")
    def validate_structure(self):
        """限制两级结构并保留唯一项目区作为版本引用入口"""
        validate_fields(self.personal_fields, PERSONAL)
        sections = {section.id: section for section in self.sections}
        if len(sections) != len(self.sections):
            raise ValueError("默认栏目标识不能重复。")
        if sum(section.kind == "projects" for section in self.sections) != 1:
            raise ValueError("须保留一个项目经历栏目，可将其隐藏。")
        for section in self.sections:
            if section.kind == "projects" and section.parent_id:
                raise ValueError("项目经历须保留为大栏目。")
            if section.parent_id:
                parent = sections.get(section.parent_id)
                if not parent or parent.id == section.id or parent.parent_id:
                    raise ValueError("子栏目只能归入其他大栏目。")
        return self
