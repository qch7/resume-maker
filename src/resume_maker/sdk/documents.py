"""文档引擎只接收已冻结的输入，插件不读取正在编辑的工作区对象"""

import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from json import loads
from pathlib import Path

from resume_maker.core.errors import Problem
from resume_maker.domain.templates import TemplatePlan
from resume_maker.sdk.model import Cancelled, ProviderError

DEFAULT_RENDERER = object()
DOCUMENT_WORK = ContextVar("document_work", default=None)


@dataclass
class DocumentWork:
    """预览请求的取消和生成预算沿渲染调用链传递"""

    cancelled: object
    deadline: float
    max_bytes: int

    def is_set(self):
        """平台执行器持续检查请求取消及总截止"""
        return self.cancelled.is_set() or time.monotonic() >= self.deadline

    def check(self, directory=None):
        """生成阶段及分页写入前后核验同一预算"""
        if self.cancelled.is_set():
            raise Cancelled("预览请求已取消。")
        if time.monotonic() >= self.deadline:
            raise ProviderError("预览排队及生成超过执行预算，请重试最新资料。")
        if (
            directory
            and sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
            > self.max_bytes
        ):
            raise ProviderError("预览生成超过临时文件容量预算，请减少图片或内容。")


@contextmanager
def document_work(cancelled, *, timeout, max_bytes):
    """保持第三方渲染器签名不变，为协作式消费者发布本轮执行上下文"""
    work = DocumentWork(cancelled, time.monotonic() + timeout, max_bytes)
    token = DOCUMENT_WORK.set(work)
    try:
        work.check()
        yield work
    finally:
        DOCUMENT_WORK.reset(token)


def current_document_work():
    """文档执行消费者只读取当前调用的取消上下文"""
    return DOCUMENT_WORK.get()


def check_document_work(directory=None):
    """正式导出没有预览预算，预览各阶段必须响应取消"""
    if work := current_document_work():
        work.check(directory)


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


def generate_docx(
    output, document, projects, *, engine, template_data=None, plan=None, template_engine=None
):
    """正式导出、预览和模板试填共享输入副本及引擎调用规则"""
    if template_data is None:
        engine(output, document, projects)
        return
    if template_engine is None:
        raise Problem("此文档需要的模板引擎未启用。", 409)
    source = output.parent / "input-template.docx"
    source.write_bytes(template_data)
    template_engine(source, output, TemplatePlan.model_validate(plan), document, projects)
