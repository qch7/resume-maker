"""为未保存的资料生成临时 Word 模板预览"""

import threading
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from resume_maker.core.errors import Problem, need
from resume_maker.domain.extensions import display_document
from resume_maker.infrastructure.database import dump, uid
from resume_maker.integrations.sources import digest
from resume_maker.integrations.word.full_resume import write_full_resume
from resume_maker.services.document_inputs import freeze_preview, generate_docx
from resume_maker.services.documents import DEFAULT_RENDERER, fill_template, render_word


class ResumePreviews:
    """串行渲染并复用相同输入，临时文件随应用实例回收"""

    def __init__(
        self,
        catalog,
        data_dir,
        *,
        render=DEFAULT_RENDERER,
        templates=True,
        engine=write_full_resume,
        registry=None,
    ):
        """仅保存依赖，首次预览时才创建临时目录"""
        self.catalog, self.data_dir = catalog, data_dir
        self.renderer, self.templates_enabled = render, templates
        self.engine = engine
        self.registry = registry
        self.template_engine = fill_template if templates else None
        self.lock = threading.Lock()
        self.directory = None
        self.results, self.cache = {}, {}
        self.templates = {}
        self.stopped = False

    def render(self, template_id, document, items, *, engine_id=None, renderer_id=None):
        """核验固定版本归属后使用当前资料和可选工作副本试填"""
        inputs = freeze_preview(self.catalog, self.data_dir, template_id, document, items)
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
            if key in self.cache:
                return dict(self.cache[key])
            if self.directory is None:
                workspace = self.data_dir / "workspaces"
                workspace.mkdir(parents=True, exist_ok=True)
                self.directory = TemporaryDirectory(prefix="resume-previews-", dir=workspace)
            identifier = uid()
            directory = Path(self.directory.name) / identifier
            directory.mkdir()
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
            renderer = render_word if self.renderer is DEFAULT_RENDERER else self.renderer
            if self.registry:
                renderer = selected_renderer.value.render if selected_renderer else None
            pages, error = (
                renderer(output, directory / "resume.pdf")
                if renderer
                else (None, "Word 精确渲染未启用，可使用内容预览。")
            )
            result = {"id": identifier, "pages": pages, "render_error": error}
            self.results[identifier] = result
            self.templates[identifier] = template_id
            if pages:
                self.cache[key] = result
            return dict(result)

    def file(self, identifier, filename):
        """只提供当前实例已生成的预览文件，模板源文件和任意路径均不可下载"""
        # 读已发布结果不占用渲染锁，更新下一版时上一版图片仍能立即加载
        result = need(self.results.get(identifier), "预览已失效，请重新生成。")
        allowed = {"resume.docx"}
        if result["pages"]:
            allowed.add("resume.pdf")
            allowed.update(f"page-{i}.png" for i in range(1, result["pages"] + 1))
            allowed.update(f"page-{i}.svg" for i in range(1, result["pages"] + 1))
        if filename not in allowed:
            raise Problem("预览文件不存在。", 404)
        path = Path(self.directory.name) / identifier / filename
        if not path.is_file():
            raise Problem("预览文件已失效，请重新生成。", 404)
        return path

    def stop(self):
        """请求结束后回收本实例创建的预览目录，正式简历和导出文件不受影响"""
        with self.lock:
            self.stopped = True
            self.results.clear()
            self.cache.clear()
            self.templates.clear()
            if self.directory:
                self.directory.cleanup()
