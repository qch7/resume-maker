"""启动变量只进入类型化配置，文件值不写入进程环境"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Literal

from dotenv.parser import parse_stream
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

PREFIX = "RESUME_MAKER_"
DEFAULT_PORT = 8765
LaunchProfile = Literal["minimal", "standard"]
PROVIDER_KEY = PREFIX + "PROVIDER_KEY"
INTERNAL_VARIABLES = frozenset({PROVIDER_KEY, PREFIX + "TEST_NATIVE_CLI"})
BOOLEAN_VALUES = {
    "1": True,
    "true": True,
    "yes": True,
    "on": True,
    "0": False,
    "false": False,
    "no": False,
    "off": False,
}


class LaunchConfigurationError(ValueError):
    """配置诊断只显示字段和来源，不包含未经确认的输入值"""


class LaunchSettings(BaseModel):
    """宿主启动参数独立于业务设置、插件配置和每次生成的实例身份"""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    port: int = Field(default=DEFAULT_PORT, ge=1, le=65535, description="本机监听端口")
    data_dir: Path | None = Field(default=None, description="正式资料目录")
    frontend_dir: Path | None = Field(default=None, description="静态资源目录覆盖")
    profile: LaunchProfile | None = Field(default=None, description="启动插件组合覆盖")
    plugin_config: Path | None = Field(default=None, description="插件启动配置文件")
    open_browser: bool = Field(default=True, description="启动时打开浏览器")

    @field_validator("port", mode="before")
    @classmethod
    def integer_port(cls, value):
        """端口只接受整数，拒绝布尔值和隐式浮点转换"""
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError("端口须为整数")
        if isinstance(value, str) and not re.fullmatch(r"[0-9]+", value.strip()):
            raise ValueError("端口须为整数")
        return value

    @field_validator("open_browser", mode="before")
    @classmethod
    def boolean_browser(cls, value):
        """布尔输入使用跨平台一致的明确拼写"""
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in BOOLEAN_VALUES:
            return BOOLEAN_VALUES[value.strip().lower()]
        raise ValueError("布尔配置须使用 true/false、1/0、yes/no 或 on/off")

    @field_validator("data_dir", "frontend_dir", "plugin_config", "profile", mode="before")
    @classmethod
    def optional_value(cls, value):
        """可选空值明确清除低优先级覆盖，目录位置继续使用产品默认"""
        return value.strip() or None if isinstance(value, str) else value


LAUNCH_VARIABLES = {PREFIX + name.upper(): name for name in LaunchSettings.model_fields}
PATH_FIELDS = frozenset({"data_dir", "frontend_dir", "plugin_config"})


def launch_environment(environment: Mapping[str, str] | None = None, *, validate=False):
    """大小写统一后只提取启动变量，内部传输标识不进入启动配置"""
    result = {}
    for key, value in (os.environ if environment is None else environment).items():
        canonical = key.upper()
        if not canonical.startswith(PREFIX):
            continue
        if canonical not in LAUNCH_VARIABLES:
            if validate and canonical not in INTERNAL_VARIABLES:
                raise LaunchConfigurationError(f"未知启动变量：{canonical}")
            continue
        if canonical in result and result[canonical] != value:
            raise LaunchConfigurationError(f"启动变量的大小写重复定义：{canonical}")
        result[canonical] = value
    return result


def environment_path(name: str):
    """程序式 Config 保留既有目录环境覆盖，不自动加载配置文件"""
    field = LAUNCH_VARIABLES[name]
    raw = launch_environment().get(name)
    if raw is None:
        return None
    settings = validated_settings({field: raw}, {field: "environment"})
    path = getattr(settings, field)
    return path.expanduser().resolve() if path is not None else None


def file_environment(path: Path):
    """使用 dotenv 语法读取明确文件，拒绝错误语法、重复项和非启动变量"""
    try:
        source = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise LaunchConfigurationError("无法读取 UTF-8 启动配置文件，请检查 --env-file") from exc
    result = {}
    for binding in parse_stream(StringIO(source)):
        line = binding.original.line
        if binding.error:
            raise LaunchConfigurationError(f"启动配置文件第 {line} 行语法无效")
        if binding.key is None:
            continue
        key = binding.key
        if key not in LAUNCH_VARIABLES:
            raise LaunchConfigurationError(f"启动配置文件第 {line} 行包含未声明变量")
        if key in result:
            raise LaunchConfigurationError(f"启动配置文件第 {line} 行重复定义 {key}")
        if binding.value is None:
            raise LaunchConfigurationError(f"启动配置文件第 {line} 行缺少赋值")
        if "${" in binding.value:
            raise LaunchConfigurationError(f"启动配置文件第 {line} 行不支持变量插值")
        result[key] = binding.value
    return result


def validated_settings(values, sources):
    """校验最终有效值，错误仅列字段、来源和错误类别"""
    try:
        return LaunchSettings.model_validate(values)
    except ValidationError as exc:
        fields = [
            f"{PREFIX}{issue['loc'][0].upper()} ({sources.get(issue['loc'][0], 'default')}): "
            f"{issue['type']}"
            for issue in exc.errors(include_input=False, include_url=False)
        ]
        raise LaunchConfigurationError("启动配置无效：" + "; ".join(fields)) from exc


@dataclass(frozen=True)
class ResolvedLaunch:
    """有效配置记录逐字段来源，诊断不包含实例令牌或进程环境"""

    settings: LaunchSettings
    sources: dict[str, str]
    env_file: Path | None

    def public_values(self, *, data_dir: Path, frontend: Path):
        """只输出固定启动字段，补齐实际使用的默认目录"""
        return {
            **self.settings.model_dump(mode="json"),
            "data_dir": str(data_dir),
            "frontend_dir": str(frontend),
            "frontend_override": self.settings.frontend_dir is not None,
            "env_file": str(self.env_file) if self.env_file is not None else None,
            "sources": self.sources,
        }


def resolve_launch(*, environment=None, env_file=None, overrides=None, cwd=None):
    """按文件、进程环境和显式参数依次覆盖，路径按所属来源位置解析"""
    directory = Path.cwd() if cwd is None else Path(cwd)
    directory = directory.resolve()
    path = Path(env_file).expanduser() if env_file is not None else None
    if path is not None:
        path = (directory / path).resolve()
    layers = []
    if path is not None:
        layers.append(("env_file", file_environment(path), path.parent))
    layers.append(("environment", launch_environment(environment, validate=True), directory))
    explicit = overrides or {}
    if set(explicit) - LaunchSettings.model_fields.keys():
        raise LaunchConfigurationError("显式启动配置包含未声明字段")
    layers.append(("cli", {PREFIX + k.upper(): v for k, v in explicit.items()}, directory))
    values = {}
    sources = dict.fromkeys(LaunchSettings.model_fields, "default")
    bases = {}
    for source, layer, base in layers:
        for key, value in layer.items():
            field = LAUNCH_VARIABLES[key]
            values[field], sources[field], bases[field] = value, source, base
    settings = validated_settings(values, sources)
    for field in PATH_FIELDS:
        if (value := getattr(settings, field)) is not None:
            values[field] = (bases[field] / value.expanduser()).resolve()
    settings = validated_settings({**settings.model_dump(), **values}, sources)
    return ResolvedLaunch(settings, sources, path)
