"""资料来源提供方的有界分页、固定身份及确认内容契约"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import ConfigDict, Field

from resume_maker.sdk.manifest import Contract


class SourceField(Contract):
    """来源拥有字段值，简历保留自己的标签和显隐"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(max_length=50)
    value: str = Field(max_length=1000)
    visible: bool = False


class SourceItem(Contract):
    """只有已核对内容可以发布，来源消失时保留简历中的最后快照"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)
    title: str = Field(max_length=300)
    subtitle: str = Field(default="", max_length=500)
    period: str = Field(default="", max_length=100)
    details: str = Field(default="", max_length=10000)
    custom_fields: tuple[SourceField, ...] = Field(default=(), max_length=25)


class SourcePage(Contract):
    """调用方按游标继续读取，单页最多提供一百条资料"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[SourceItem, ...] = Field(max_length=100)
    cursor: str | None = Field(default=None, max_length=1000)


class SourceReader(Protocol):
    """来源查询共用调用方的读取快照，不能提交业务写入"""

    def all(self, sql: str, args=()) -> list[dict]:
        """执行所声明 SQL 存储协议的只读查询"""
        ...

    def setting(self, key: str, default=None):
        """在同一个读取快照取得来源拥有的设置"""
        ...


@dataclass(frozen=True)
class ResumeSource:
    """非代码资料通过同一来源契约供简历选择和同步"""

    title: str
    version: str
    browse: Callable[[SourceReader, str | None, str, int], SourcePage]
    resolve: Callable[[SourceReader, tuple[str, ...]], tuple[SourceItem, ...]]
    api_version: str = "1.0.0"
