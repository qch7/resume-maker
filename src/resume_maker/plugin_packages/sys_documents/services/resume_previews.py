"""为未保存的资料生成临时 Word 模板预览"""

import threading
import time
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, replace

from resume_maker.core.content import digest
from resume_maker.core.errors import Problem
from resume_maker.domain.extensions import display_document
from resume_maker.domain.layout_fit import FIT_TIMEOUT_SECONDS
from resume_maker.plugin_packages.sys_documents.configuration import Settings
from resume_maker.plugin_packages.sys_documents.services.preview_fit import fit_preview
from resume_maker.sdk.documents import check_document_work, document_work, generate_docx
from resume_maker.sdk.observation import internal
from resume_maker.sdk.previews import PreviewCache
from resume_maker.sdk.records import dump


@dataclass
class FrozenPreview:
    """候选共用同一份资料、模板字节及已选择的引擎实现"""

    inputs: object
    resume: dict
    projects: list
    template: dict
    engine: object
    renderer: object
    engine_stamp: list
    template_id: str | None


class ResumePreviews:
    """串行渲染并复用相同输入，临时文件随应用实例回收"""

    def __init__(
        self,
        catalog,
        data_dir,
        *,
        render=None,
        templates=False,
        engine,
        template_engine=None,
        registry=None,
        settings=None,
    ):
        """仅保存依赖，首次预览时才创建临时目录"""
        self.catalog, self.data_dir = catalog, data_dir
        self.renderer, self.templates_enabled = render, templates
        self.engine = engine
        self.registry = registry
        self.template_engine = template_engine
        self.settings = settings or Settings()
        self.lock = threading.Lock()
        self.directory = None
        self.results, self.cache = {}, {}
        self.templates = {}
        self.stopped = False
        self.admission = threading.Lock()
        self.requests = {}
        self.request_context = ContextVar("resume_preview_request", default=None)
        self.failures = {}
        self.pool = PreviewCache(data_dir / "workspaces", prefix="resume-previews-")

    @internal
    @contextmanager
    def request_work(self, cancelled=None, *, timeout=None):
        """在线程池排队前固定准入、截止，实际工作结束后才释放"""
        flag = cancelled if cancelled is not None else threading.Event()
        request_key = object()
        with self.admission:
            if self.stopped:
                raise Problem("应用正在关闭。", 409)
            if len(self.requests) >= self.settings.max_preview_requests:
                raise Problem("预览队列已满，请等待当前预览结束后重试。", 429)
            self.requests[request_key] = flag
        try:
            budget = (
                min(self.settings.preview_timeout_seconds, timeout)
                if timeout is not None
                else self.settings.preview_timeout_seconds
            )
            with document_work(
                flag,
                timeout=budget,
                max_bytes=self.pool.max_bytes,
            ) as work:
                token = self.request_context.set((work, work.deadline - budget))
                try:
                    yield work
                finally:
                    self.request_context.reset(token)
        finally:
            with self.admission:
                self.requests.pop(request_key, None)

    def render(
        self,
        template_id,
        document,
        items,
        *,
        engine_id=None,
        renderer_id=None,
        cancelled=None,
        force=False,
        timeout=None,
    ):
        """沿用请求原有预算，直接同步调用则创建独立的准入作用域"""
        context = self.request_context.get()
        work = context[0] if context is not None else None
        if work is not None and cancelled is not None and cancelled is not work.cancelled:
            raise Problem("预览取消信号不属于当前请求。", 409)
        with (
            nullcontext(work) if work is not None else self.request_work(cancelled, timeout=timeout)
        ):
            with self.render_lock():
                return self._render(
                    template_id,
                    document,
                    items,
                    engine_id=engine_id,
                    renderer_id=renderer_id,
                    force=force,
                )

    def fit(
        self,
        template_id,
        document,
        items,
        *,
        engine_id=None,
        renderer_id=None,
        cancelled=None,
        force=False,
        timeout=None,
    ):
        """在同一次取消作用域内冻结资料，顺序实测候选且只发布最终结果"""
        context = self.request_context.get()
        work = context[0] if context is not None else None
        if work is not None and cancelled is not None and cancelled is not work.cancelled:
            raise Problem("预览取消信号不属于当前请求。", 409)
        timeout = FIT_TIMEOUT_SECONDS if timeout is None else min(timeout, FIT_TIMEOUT_SECONDS)
        if work is not None:
            # 公共服务调用也从最初准入起计时，已有较短截止不能被延后
            work.deadline = min(work.deadline, context[1] + timeout)
        with (
            nullcontext(work) if work is not None else self.request_work(cancelled, timeout=timeout)
        ):
            with self.render_lock():
                frozen = self._freeze(template_id, document, items, engine_id, renderer_id)
                return fit_preview(self, frozen, force=force)

    @contextmanager
    def render_lock(self):
        """未开始的预览可取消，不占住已运行请求的资源"""
        while not self.lock.acquire(timeout=0.05):
            check_document_work()
        try:
            check_document_work()
            yield
        finally:
            self.lock.release()

    def _render(self, template_id, document, items, *, engine_id, renderer_id, force):
        """固定输入后复用同键结果，成功及短暂失败均合并重复工作"""
        frozen = self._freeze(template_id, document, items, engine_id, renderer_id)
        with self.measure(frozen, display_document(frozen.resume["document"]), force) as measured:
            return self.publish(frozen, measured)

    def _freeze(self, template_id, document, items, engine_id, renderer_id):
        """只读取一次资料及模板，候选之间不重新读取可变来源"""
        inputs = self.catalog.freeze_preview(self.data_dir, template_id, document, items)
        resume, projects, template = inputs.values()
        if template and not self.templates_enabled and not self.registry:
            raise Problem("此简历引用的模板引擎未启用，内容仍保留。", 409)
        selected_engine = (
            self.registry.engine(engine_id, template=bool(template)) if self.registry else None
        )
        selected_renderer = self.registry.renderer(renderer_id) if self.registry else None
        if not self.registry and (engine_id or renderer_id):
            raise Problem("当前文档预览未连接引擎注册表。", 409)
        engine_stamp = [
            (item.identifier, item.value.version) if item else None
            for item in (selected_engine, selected_renderer)
        ]
        if self.stopped:
            raise Problem("应用正在关闭。", 409)
        if template_id:
            self.catalog.template(template_id)
        return FrozenPreview(
            inputs,
            resume,
            projects,
            template,
            selected_engine,
            selected_renderer.value.render
            if self.registry and selected_renderer
            else (None if self.registry else self.renderer),
            engine_stamp,
            template_id,
        )

    @contextmanager
    def measure(self, frozen, document, force=False):
        """从冻结原件生成独立候选，未选中的临时文件在作用域结束时回收"""
        check_document_work()
        key = digest(
            dump(
                {
                    "template": frozen.template,
                    "document": document,
                    "projects": frozen.projects,
                    "engines": frozen.engine_stamp,
                }
            ).encode()
        )
        if not force and key in self.cache and self.pool.touch(self.cache[key]["id"]):
            yield {"key": key, "result": dict(self.cache[key]), "directory": None}
            return
        failed = self.failures.get(key)
        if (
            not force
            and failed
            and failed[1] > time.monotonic()
            and self.pool.touch(failed[0]["id"])
        ):
            yield {"key": key, "result": dict(failed[0]), "directory": None}
            return
        with self.pool.allocate() as (identifier, directory):
            self.directory = self.pool.directory
            output = directory / "resume.docx"
            if frozen.engine:
                frozen.engine.value.generate(
                    output,
                    replace(
                        frozen.inputs,
                        resume_json=dump({**frozen.resume, "document": document}),
                    ),
                )
            else:
                generate_docx(
                    output,
                    document,
                    deepcopy(frozen.projects),
                    engine=self.engine,
                    template_data=frozen.inputs.template_bytes,
                    plan=frozen.template["mapping"]["plan"] if frozen.template else None,
                    template_engine=self.template_engine,
                )
            if not output.is_file():
                raise Problem("文档引擎未生成声明的 DOCX 文件。", 409)
            check_document_work(directory)
            pages, error = (
                frozen.renderer(output, directory / "resume.pdf")
                if frozen.renderer
                else (None, "Word 精确渲染未启用，可使用内容预览。")
            )
            check_document_work(directory)
            result = {"id": identifier, "pages": pages, "render_error": error}
            yield {"key": key, "result": result, "directory": directory}

    def publish(self, frozen, measured):
        """发布前再次核验截止，只登记最终候选并复用普通预览缓存"""
        result, directory = measured["result"], measured["directory"]
        check_document_work(directory)
        if directory is None:
            return dict(result)
        identifier, pages, key = result["id"], result["pages"], measured["key"]
        files = {"resume.docx"}
        if pages:
            files.add("resume.pdf")
            files.update(f"page-{i}.{ext}" for i in range(1, pages + 1) for ext in ("png", "svg"))
        evicted = self.pool.publish(identifier, directory, files, owner=frozen.template_id)
        for old in evicted:
            self.results.pop(old, None)
            self.templates.pop(old, None)
        self.cache = {key: value for key, value in self.cache.items() if value["id"] not in evicted}
        self.failures = {
            key: value for key, value in self.failures.items() if value[0]["id"] not in evicted
        }
        self.results[identifier] = result
        self.templates[identifier] = frozen.template_id
        if pages:
            self.cache[key] = result
            self.failures.pop(key, None)
        else:
            self.failures[key] = (
                result,
                time.monotonic() + self.settings.failed_preview_retry_seconds,
            )
        return dict(result)

    def file(self, identifier, filename):
        """只提供当前实例已生成的预览文件，模板源文件、任意路径均不可下载"""
        return self.pool.file(identifier, filename)

    def lease(self, identifier, filename):
        """下载响应持有独立租约，不等待正在渲染的新结果"""
        return self.pool.lease(identifier, filename)

    @internal
    @contextmanager
    def maintenance(self):
        """公开预览维护屏障，调用方持有期间阻止创建迟到缓存"""
        with self.lock, self.pool.lock:
            yield

    def template_artifacts(self, template_id):
        """返回目标模板的临时预览路径，不暴露可修改的内部索引"""
        return self.pool.artifacts(template_id)

    def invalidate_template(self, template_id):
        """在维护屏障内撤销已清理的预览、缓存"""
        self.pool.discard(template_id)
        identifiers = {key for key, value in self.templates.items() if value == template_id}
        for key in identifiers:
            self.results.pop(key, None)
            self.templates.pop(key, None)
        self.cache = {
            key: value for key, value in self.cache.items() if value["id"] not in identifiers
        }
        self.failures.clear()

    def stop(self):
        """请求结束后回收本实例创建的预览目录，正式简历、导出文件不受影响"""
        with self.admission:
            self.stopped = True
            for flag in self.requests.values():
                flag.set()
        with self.lock:
            self.results.clear()
            self.cache.clear()
            self.failures.clear()
            self.templates.clear()
            self.pool.stop()
            self.directory = None
