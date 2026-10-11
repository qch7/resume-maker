"""无执行副作用的插件清单和明确版本区间"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

IDENTIFIER = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
VERSION = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"


class Contract(BaseModel):
    """拒绝拼写错误和无法解释的清单字段"""

    model_config = ConfigDict(extra="forbid", frozen=True)


def compatible(version: str, constraint: str) -> bool:
    """比较稳定 SemVer 的精确值和空格分隔区间，不混用 Python 包版本"""
    if not re.fullmatch(VERSION, version):
        raise ValueError(f"非法协议版本：{version}")
    actual = tuple(int(part) for part in version.split("."))
    if not constraint.strip():
        raise ValueError("版本区间不能为空")
    for term in constraint.split():
        match = re.fullmatch(r"(>=|<=|>|<|=)?(\d+\.\d+\.\d+)", term)
        if not match or not re.fullmatch(VERSION, match[2]):
            raise ValueError(f"非法版本区间：{constraint}")
        expected = tuple(int(part) for part in match[2].split("."))
        comparison = {
            ">=": actual >= expected,
            "<=": actual <= expected,
            ">": actual > expected,
            "<": actual < expected,
            "=": actual == expected,
        }
        if not comparison[match[1] or "="]:
            return False
    return True


class Entry(Contract):
    """入口位置及实际信任模式"""

    mode: Literal["trusted-host", "worker", "trusted-client", "isolated-client"]
    entry: str = Field(min_length=1)


class Service(Contract):
    """能力的协议版本、基数及可选显示名称"""

    version: str = Field(default="1.0.0", pattern=VERSION)
    cardinality: Literal["one", "many"] = "one"
    title: str | None = Field(default=None, min_length=1, max_length=100)


class Dependency(Contract):
    """依赖可以约束版本、集合基数和明确提供方，避免隐式抢占"""

    version: str = ">=1.0.0 <2.0.0"
    cardinality: Literal["one", "many"] = "one"
    provider: str | None = None


class Instances(Contract):
    """实例身份和可用范围"""

    scope: Literal["application", "workspace", "task"] = "workspace"
    multiple: bool = False


class InstanceSpec(Contract):
    """实例使用稳定身份，提供方绑定按执行域和能力逐项声明"""

    id: str = Field(pattern=IDENTIFIER)
    plugin: str = Field(pattern=IDENTIFIER)
    bindings: dict[str, dict[str, str]] = Field(default_factory=dict)


class Lifecycle(Contract):
    """按实际变更类型声明生效方式"""

    toggle: Literal["live", "drain", "host-restart"] = "drain"
    config_update: Literal["live", "drain", "worker-restart", "host-restart"] = "drain"
    host_code_update: Literal["host-restart", "worker-restart"] = "host-restart"
    client_code_update: Literal["client-reload"] = "client-reload"
    deactivate_timeout_seconds: int = Field(default=30, ge=1, le=300)


class DataDescriptor(Contract):
    """停用后仍保留的非执行数据目录"""

    schema_version: int = Field(default=1, ge=1)
    privacy_settings: list[str] = Field(default_factory=list)
    reads: list[int] = Field(default_factory=lambda: [1])
    writes: list[int] = Field(default_factory=lambda: [1])
    tables: list[str] = Field(default_factory=list)
    settings: list[str] = Field(default_factory=list)
    folders: list[str] = Field(default_factory=list)
    descriptor: str | None = None
    migrations: list[str] = Field(default_factory=list)
    schemas: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    backup: bool = True


class RpcMethod(Contract):
    """跨进程只传递经过版本化 JSON Schema 校验的数据"""

    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    timeout_seconds: int = Field(default=30, ge=1, le=7200)


class CredentialField(Contract):
    """顶层配置字段只承载引用，密码由宿主独立保存"""

    purpose: str = Field(pattern=IDENTIFIER)
    title: str = Field(min_length=1, max_length=100)


class CapabilityGroup(Contract):
    """插件所属的产品能力分类，不参与服务版本及依赖求解"""

    id: str = Field(pattern=IDENTIFIER)
    title: str = Field(min_length=1, max_length=100)


class Manifest(Contract):
    """安装前可读取的版本化插件定义，系统身份由发行策略判定"""

    manifest_version: Literal[1] = 1
    id: str = Field(pattern=IDENTIFIER)
    version: str = Field(pattern=VERSION)
    package: str
    title: str
    capability_groups: list[CapabilityGroup] = Field(default_factory=list, max_length=20)
    host_api: str = ">=1.0.0 <2.0.0"
    client_api: str = ">=1.0.0 <2.0.0"
    instances: Instances = Field(default_factory=Instances)
    entrypoints: dict[str, Entry] = Field(default_factory=dict)
    requires: dict[str, dict[str, str | Dependency]] = Field(default_factory=dict)
    optional: dict[str, str] = Field(default_factory=dict)
    enhances: list[str] = Field(default_factory=list)
    plugins: dict[str, str] = Field(default_factory=dict)
    provides: dict[str, dict[str, Service]] = Field(default_factory=dict)
    contributes: dict[str, list[str]] = Field(default_factory=dict)
    consumes: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    environment_lock: str | None = None
    config: dict[str, JsonValue] = Field(default_factory=dict)
    credential_fields: dict[str, CredentialField] = Field(default_factory=dict)
    config_schema: dict[str, JsonValue] = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )
    data: DataDescriptor | None = None
    lifecycle: Lifecycle = Field(default_factory=Lifecycle)
    compatibility: dict[str, str] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    rpc: dict[str, RpcMethod] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_protocol(self):
        """入口域和版本区间必须能在导入代码前得到确定解释"""
        compatible("1.0.0", self.host_api)
        compatible("1.0.0", self.client_api)
        for group in self.requires.values():
            for value in group.values():
                compatible("1.0.0", value if isinstance(value, str) else value.version)
        for value in (*self.plugins.values(), *self.optional.values()):
            compatible("1.0.0", value)
        allowed = {
            "host": {"trusted-host"},
            "worker": {"worker"},
            "client": {"trusted-client", "isolated-client"},
        }
        for domain, entry in self.entrypoints.items():
            if domain not in allowed or entry.mode not in allowed[domain]:
                raise ValueError(f"入口域和模式不一致：{domain}/{entry.mode}")
        if set(self.requires) - {"host", "client", "remote"}:
            raise ValueError("依赖执行域仅支持 host、client 和 remote")
        if set(self.provides) - {"host", "client"}:
            raise ValueError("提供能力须声明在 host 或 client 执行域")
        properties = self.config_schema.get("properties", {})
        if self.credential_fields and not isinstance(properties, dict):
            raise ValueError("凭据字段须在 config_schema.properties 中声明")
        for name in self.credential_fields:
            schema = properties.get(name, {})
            if (
                not re.fullmatch(IDENTIFIER, name)
                or not isinstance(schema, dict)
                or schema.get("type") != "string"
                or schema.get("format") != "credential-ref"
            ):
                raise ValueError("凭据字段须声明为顶层 string 和 credential-ref 格式")
            for default in (schema.get("default", ""), self.config.get(name, "")):
                if not isinstance(default, str) or (
                    default and not re.fullmatch(r"cred\.[a-f0-9]{32}", default)
                ):
                    raise ValueError("凭据字段的默认值只能为空字符串或不透明引用")
        if self.credential_fields and "credentials" not in self.requires.get("host", {}):
            raise ValueError("凭据字段须声明 host/credentials 依赖")
        return self
