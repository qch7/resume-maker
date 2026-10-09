"""文档导入契约：原件固定，探测无副作用，结果交由业务事务发布"""

from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from re import fullmatch
from threading import Event
from typing import Literal

from resume_maker.domain.models import ProviderSettings
from resume_maker.sdk.manifest import VERSION, compatible
from resume_maker.sdk.model import Provider

ImportPurpose = Literal["template", "certificate"]


@dataclass(frozen=True)
class ImportSource:
    """插件只获得本轮原件字节，文件名仅作为显示及格式提示"""

    filename: str
    data: bytes = field(repr=False)
    purpose: ImportPurpose = "template"

    @property
    def sha256(self) -> str:
        """记录实际原件摘要以核对重试输入"""
        return sha256(self.data).hexdigest()


@dataclass(frozen=True)
class ImportProbe:
    """探测返回实际格式和源页数，无法确定分页的 DOCX 可不声明页数"""

    format: str
    pages: int | None = None


@dataclass(frozen=True)
class ImportResult:
    """模板返回 DOCX 字节，证书返回每页 PNG 字节，禁止用外部路径代替结果"""

    template: bytes | None = field(default=None, repr=False)
    pages: tuple[bytes, ...] = field(default=(), repr=False)
    text: str = ""
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportContext:
    """本轮暂存空间和取消信号，模型调用只能使用系统注入的隐私出口"""

    workspace: Path
    cancelled: Event
    provider: Provider | None = None
    settings: ProviderSettings | None = None
    document_json: str = "{}"
    projects_json: str = "[]"
    emit: Callable[[str, dict], None] | None = None
    renderer: Callable | None = None


@dataclass(frozen=True)
class DocumentImporter:
    """声明支持的用途及格式，探测必须检查字节且不得调用模型或写入业务资料"""

    version: str
    title: str
    purposes: tuple[ImportPurpose, ...]
    extensions: tuple[str, ...]
    probe: Callable[[ImportSource], ImportProbe | None]
    prepare: Callable[[ImportSource, ImportContext], ImportResult]
    api_version: str = "1.0.0"
    uses_renderer: bool = False

    def __post_init__(self):
        """构造时拒绝不完整声明，让激活事务能回收错误贡献"""
        if (
            not isinstance(self.version, str)
            or not fullmatch(VERSION, self.version)
            or not isinstance(self.api_version, str)
            or not fullmatch(VERSION, self.api_version)
            or not compatible(self.api_version, ">=1.0.0 <2.0.0")
            or not isinstance(self.title, str)
            or not 1 <= len(self.title) <= 120
            or not isinstance(self.purposes, tuple)
            or not self.purposes
            or any(value not in ("template", "certificate") for value in self.purposes)
            or not isinstance(self.extensions, tuple)
            or not self.extensions
            or any(
                not isinstance(value, str) or not fullmatch(r"\.[a-z0-9]{1,16}", value)
                for value in self.extensions
            )
            or not callable(self.probe)
            or not callable(self.prepare)
            or type(self.uses_renderer) is not bool
        ):
            raise ValueError("文档导入器声明无效或协议不兼容")
