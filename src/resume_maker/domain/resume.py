"""个人信息与两级简历栏目；独立于项目经历的固定版本引用"""

import base64
import binascii
from typing import Literal

from pydantic import Field, model_validator

from resume_maker.domain.honor_entries import HONOR_CUSTOM_IDS
from resume_maker.domain.models import (
    CustomInfoField,
    DefaultField,
    Model,
    ProjectVisibility,
    validate_custom_field_ids,
)

PersonalField = Literal[
    "name", "job_title", "gender", "age", "phone", "email", "gpa", "location", "website", "photo"
]
EntryField = Literal["title", "subtitle", "period", "details"]


class PersonalInfo(Model):
    """固定展示在简历顶部的基本信息；空字段不参与排版"""

    name: str = Field(default="", max_length=100)
    job_title: str = Field(default="", max_length=200)
    gender: str = Field(default="", max_length=30)
    age: str = Field(default="", max_length=30)
    phone: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=200)
    gpa: str = Field(default="", max_length=100)
    location: str = Field(default="", max_length=200)
    website: str = Field(default="", max_length=500)
    photo: str = Field(default="", max_length=2_000_000)
    hidden_fields: list[PersonalField] = Field(default_factory=list, max_length=10)
    custom_fields: list[CustomInfoField] = Field(default_factory=list, max_length=20)
    field_definitions: list[DefaultField] | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def validate_photo(self):
        """只接受大小受限的 PNG/JPEG 内嵌照片且不读取外部 URL 或本机路径"""
        validate_custom_field_ids(self.custom_fields)
        if not self.photo:
            return self
        prefix, _, encoded = self.photo.partition(",")
        if prefix not in {"data:image/png;base64", "data:image/jpeg;base64"}:
            raise ValueError("照片须为 PNG 或 JPEG 图片。")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("照片数据无效。") from exc
        if not raw.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
            raise ValueError("照片数据无效。")
        return self


class SectionEntry(Model):
    """栏目下的经历或文本条目；支持学校、专业、时间与多行正文"""

    id: str = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=300)
    subtitle: str = Field(default="", max_length=500)
    period: str = Field(default="", max_length=100)
    details: str = Field(default="", max_length=10000)
    visible: bool = True
    hidden_fields: list[EntryField] = Field(default_factory=list, max_length=4)
    custom_fields: list[CustomInfoField] = Field(default_factory=list, max_length=25)
    field_definitions: list[DefaultField] | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def validate_custom_fields(self):
        """校验本条经历的自定义信息标识；允许各条经历独立使用字段名称"""
        validate_custom_field_ids(self.custom_fields)
        if sum(field.id not in HONOR_CUSTOM_IDS for field in self.custom_fields) > 20:
            raise ValueError("每条资料最多保留 20 项自定义信息。")
        return self


class ResumeSection(Model):
    """可排序、隐藏或归入大栏目的栏目；项目区使用独立版本引用"""

    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=100)
    kind: Literal["education", "projects", "text"] = "text"
    parent_id: str | None = None
    visible: bool = True
    entries: list[SectionEntry] = Field(default_factory=list, max_length=100)
    field_definitions: list[DefaultField] | None = Field(default=None, max_length=30)


class ResumeDocument(Model):
    """一份简历独立保存的顶部资料与栏目编排；允许大栏目加子栏目两层"""

    personal: PersonalInfo = Field(default_factory=PersonalInfo)
    sections: list[ResumeSection] = Field(max_length=40)
    project_visibility: dict[str, ProjectVisibility] = Field(default_factory=dict, max_length=1000)

    @model_validator(mode="after")
    def validate_hierarchy(self):
        """拒绝重复标识、孤立引用、循环与超过两级的栏目；项目经历保持独立大栏目"""
        by_id = {section.id: section for section in self.sections}
        if len(by_id) != len(self.sections):
            raise ValueError("栏目标识不能重复。")
        if sum(section.kind == "projects" for section in self.sections) != 1:
            raise ValueError("须保留一个项目经历栏目，可将其隐藏。")
        for section in self.sections:
            if len({entry.id for entry in section.entries}) != len(section.entries):
                raise ValueError("同一栏目中的条目标识不能重复。")
            if section.kind == "projects" and (section.parent_id or section.entries):
                raise ValueError("项目经历使用独立的大栏目与版本引用。")
            if section.parent_id:
                parent = by_id.get(section.parent_id)
                if not parent or parent.id == section.id or parent.parent_id:
                    raise ValueError("子栏目只能归入其他大栏目。")
        return self
