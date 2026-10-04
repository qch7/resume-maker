"""文档引擎只接收已冻结的输入，插件不读取正在编辑的工作区对象"""

from collections.abc import Callable
from dataclasses import dataclass
from json import loads
from pathlib import Path


@dataclass(frozen=True)
class DocumentInput:
    """输入 JSON 和原件字节固定在同一读取事务，调用方取得独立解码副本"""

    resume_json: str
    projects_json: str
    template_json: str
    template_bytes: bytes | None

    def values(self):
        """返回本轮独立输入，防止引擎修改其他消费者持有的内容"""
        return loads(self.resume_json), loads(self.projects_json), loads(self.template_json)


@dataclass(frozen=True)
class DocumentEngine:
    """第一版引擎生成可编辑 DOCX，模板和内置版式明确区分"""

    version: str
    generate: Callable[[Path, DocumentInput], None]
    accepts_template: bool = False


@dataclass(frozen=True)
class DocumentRenderer:
    """渲染器接收已生成 DOCX，返回实际页数和可解释的环境错误"""

    version: str
    render: Callable[[Path, Path], tuple[int | None, str | None]]
