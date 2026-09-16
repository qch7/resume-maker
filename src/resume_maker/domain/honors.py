"""荣誉库与证书识别的独立数据契约。"""

from typing import Literal

from pydantic import Field, field_validator

from resume_maker.domain.models import Model

HonorCategory = Literal["竞赛获奖", "资格证书", "奖学金", "荣誉称号", "其他"]


class HonorFields(Model):
    """可核对和复用的证书资料；无法确认的信息保持空白。"""

    name: str = Field(default="", max_length=300)
    category: HonorCategory = "其他"
    level: str = Field(default="", max_length=100)
    award: str = Field(default="", max_length=200)
    issuer: str = Field(default="", max_length=500)
    date: str = Field(default="", max_length=100)
    recipient: str = Field(default="", max_length=300)
    certificate_number: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=5000)

    @field_validator("*", mode="before")
    @classmethod
    def trim_text(cls, value):
        """清除字段外围空白，保持证书编号和不完整日期的原文。"""
        return value.strip() if isinstance(value, str) else value


class HonorRecognition(Model):
    """模型提取的资料、可读原文和需要人工核对的歧义。"""

    fields: HonorFields
    text: str = Field(default="", max_length=30000)
    warnings: list[str] = Field(default_factory=list, max_length=30)


class HonorSave(Model):
    """用户确认的资料和乐观并发版本。"""

    fields: HonorFields
    version: int = Field(default=0, ge=0)
