"""为未保存的资料生成临时 Word 模板预览"""

import threading
from contextlib import contextmanager
from dataclasses import replace

from resume_maker.core.content import digest
from resume_maker.core.errors import Problem
from resume_maker.domain.extensions import display_document
from resume_maker.sdk.documents import generate_docx
from resume_maker.sdk.observation import internal
from resume_maker.sdk.previews import PreviewCache
from resume_maker.sdk.records import dump


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
    ):
        """仅保存依赖，首次预览时才创建临时目录"""
        self.catalog, self.data_dir = catalog, data_dir
        self.renderer, self.templates_enabled = render, templates
        self.engine = engine
        self.registry = registry
        self.template_engine = template_engine
        self.lock = threading.Lock()
        self.directory = None
        self.results, self.cache = {}, {}
        self.templates = {}
        self.stopped = False
        self.pool = PreviewCache(data_dir / "workspaces", prefix="resume-previews-")

    def render(self, template_id, document, items, *, engine_id=None, renderer_id=None):
        """核验固定版本归属后使用当前资料和可选工作副本试填"""
        inputs = self.catalog.freeze_preview(self.data_dir, template_id, document, items)
        resume, projects, template = inputs.values()
        if template and not self.templates_enabled and not self.registry:
            raise Problem("此简历引用的模板引擎未启用，内容仍保留。", 409)
        document = display_document(resume["document"])
        data = inputs.template_bytes
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
        key = digest(
            dump(
                {
                    "template": template,
                    "document": document,
                    "projects": projects,
                    "engines": engine_stamp,
                }
            ).encode()
        )
        with self.lock:
            if self.stopped:
                raise Problem("应用正在关闭。", 409)
            if template_id:
                self.catalog.template(template_id)
            if key in self.cache and self.pool.touch(self.cache[key]["id"]):
                return dict(self.cache[key])
            with self.pool.allocate() as (identifier, directory):
                self.directory = self.pool.directory
                output = directory / "resume.docx"
                if selected_engine:
                    selected_engine.value.generate(
                        output, replace(inputs, resume_json=dump({**resume, "document": document}))
                    )
                else:
                    generate_docx(
                        output,
                        document,
                        projects,
                        engine=self.engine,
                        template_data=data,
                        plan=template["mapping"]["plan"] if template else None,
                        template_engine=self.template_engine,
                    )
                if not output.is_file():
                    raise Problem("文档引擎未生成声明的 DOCX 文件。", 409)
                renderer = self.renderer
                if self.registry:
                    renderer = selected_renderer.value.render if selected_renderer else None
                pages, error = (
                    renderer(output, directory / "resume.pdf")
                    if renderer
                    else (None, "Word 精确渲染未启用，可使用内容预览。")
                )
                result = {"id": identifier, "pages": pages, "render_error": error}
                files = {"resume.docx"}
                if pages:
                    files.add("resume.pdf")
                    files.update(
                        f"page-{i}.{ext}" for i in range(1, pages + 1) for ext in ("png", "svg")
                    )
                evicted = self.pool.publish(identifier, directory, files, owner=template_id)
                for old in evicted:
                    self.results.pop(old, None)
                    self.templates.pop(old, None)
                self.cache = {
                    key: value for key, value in self.cache.items() if value["id"] not in evicted
                }
                self.results[identifier] = result
                self.templates[identifier] = template_id
                if pages:
                    self.cache[key] = result
                return dict(result)

    def file(self, identifier, filename):
        """只提供当前实例已生成的预览文件，模板源文件和任意路径均不可下载"""
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
        """在维护屏障内撤销已清理的预览和缓存"""
        self.pool.discard(template_id)
        identifiers = {key for key, value in self.templates.items() if value == template_id}
        for key in identifiers:
            self.results.pop(key, None)
            self.templates.pop(key, None)
        self.cache = {
            key: value for key, value in self.cache.items() if value["id"] not in identifiers
        }

    def stop(self):
        """请求结束后回收本实例创建的预览目录，正式简历和导出文件不受影响"""
        with self.lock:
            self.stopped = True
            self.results.clear()
            self.cache.clear()
            self.templates.clear()
            self.pool.stop()
            self.directory = None
