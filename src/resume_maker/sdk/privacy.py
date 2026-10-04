"""附加保护规则只登记敏感资料，不能移除系统基础保护"""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import Field, JsonValue

from resume_maker.sdk.manifest import Contract
from resume_maker.sdk.sources import SourceReader


class PrivacyValues(Contract):
    """仅在本机隐私出口消费的敏感词和结构化资料"""

    terms: tuple[str, ...] = Field(default=(), max_length=10000)
    private_data: tuple[JsonValue, ...] = Field(default=(), max_length=10000)


@dataclass(frozen=True)
class PrivacyRuleContribution:
    """规则有独立版本和本地解释，返回资料继续经过系统脱敏引擎"""

    title: str
    description: str
    version: str
    collect: Callable[[SourceReader], PrivacyValues]
    api_version: str = "1.0.0"
