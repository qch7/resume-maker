"""声明式配置操作区分业务空值、重置和整份替换"""

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from resume_maker.sdk.manifest import IDENTIFIER, Contract


class ConfigurationEdit(Contract):
    """字段路径使用属性名数组，数组值始终整体替换"""

    instance: str = Field(pattern=IDENTIFIER)
    operation: Literal["replace", "set", "reset"]
    path: tuple[str, ...] = Field(default=(), max_length=20)
    value: JsonValue = None

    @model_validator(mode="after")
    def valid_operation(self):
        """重置不携带值，替换仅接受完整配置对象"""
        if self.operation == "replace" and (self.path or not isinstance(self.value, dict)):
            raise ValueError("replace 须提供整份配置对象且不能包含字段路径")
        if self.operation == "reset" and "value" in self.model_fields_set:
            raise ValueError("reset 不能携带 value，业务空值请使用 set")
        if self.operation == "set" and (not self.path or "value" not in self.model_fields_set):
            raise ValueError("set 须明确字段路径和 value")
        if any(not key or len(key) > 200 for key in self.path):
            raise ValueError("配置字段路径无效")
        return self


class ConfigurationLayer(Contract):
    """按声明顺序覆盖配置，层名称用于逐字段来源说明"""

    name: str = Field(min_length=1, max_length=100)
    edits: tuple[ConfigurationEdit, ...] = Field(default=(), max_length=10000)
