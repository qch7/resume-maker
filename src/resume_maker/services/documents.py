"""完整简历的固定版本导出及可追溯清单"""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from resume_maker.core.content import digest
from resume_maker.core.errors import Problem
from resume_maker.domain.extensions import display_document
from resume_maker.sdk.documents import generate_docx
from resume_maker.sdk.records import dump, now, uid
from resume_maker.sdk.services import Resumes


class Documents:
    """使用内置版式或完整模板，将固定版本简历导出为 Word"""

    def __init__(
        self,
        catalog: Resumes,
        data_dir: Path,
        *,
        storage,
        assets=None,
        runtime_snapshot=None,
        render=None,
        templates=False,
        engine,
        template_engine=None,
        registry=None,
    ):
        """保存当前模块所需依赖，供后续业务操作共享使用"""
        self.catalog, self.db, self.data_dir = catalog, storage, data_dir
        self.renderer, self.templates_enabled = render, templates
        self.engine = engine
        self.registry = registry
        self.assets = assets
        self.template_engine = template_engine
        self.runtime_snapshot = runtime_snapshot

    def engines(self):
        """列出当前可选择的生成及渲染能力，停用贡献立即从列表撤销"""
        return self.registry.describe() if self.registry else {"engines": [], "renderers": []}

    def importers(self, purpose):
        """读取统一导入目录，证书和模板页面使用相同格式描述"""
        return self.registry.importers(purpose) if self.registry else []

    def export(self, resume_id: str, *, engine_id=None, renderer_id=None) -> dict:
        """使用临时工作目录生成成品，发布后只保留统一资源里的文件"""
        if self.assets is None:
            return self._export(resume_id, engine_id=engine_id, renderer_id=renderer_id)
        root = self.data_dir / "workspaces"
        root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="export-", dir=root) as directory:
            return self._export(
                resume_id, engine_id=engine_id, renderer_id=renderer_id, directory=Path(directory)
            )

    def _export(self, resume_id, *, engine_id=None, renderer_id=None, directory=None):
        """读取固定资料及项目引用，按所选完整模板或内置版式生成文件和清单"""
        inputs = self.catalog.freeze_export(self.data_dir, resume_id)
        resume, manifest_items, template = inputs.values()
        renderer = self.renderer
        engine, template_engine = self.engine, self.template_engine
        selected_engine = (
            self.registry.engine(engine_id, template=bool(template)) if self.registry else None
        )
        selected_renderer = self.registry.renderer(renderer_id) if self.registry else None
        if self.registry:
            renderer = selected_renderer.value.render if selected_renderer else None
        elif engine_id or renderer_id:
            raise Problem("当前文档流程未连接引擎注册表。", 409)
        runtime = self.runtime_snapshot() if self.runtime_snapshot else {}
        if template and not self.templates_enabled and not self.registry:
            raise Problem("此简历引用了已停用的模板引擎，请启用后导出或另存内置版式。", 409)
        displayed = display_document(resume["document"])
        export_id = uid()
        if directory is None:
            directory = self.data_dir / "exports" / export_id
            directory.mkdir(parents=True)
        output = directory / "resume.docx"
        if selected_engine:
            selected_engine.value.generate(
                output, replace(inputs, resume_json=dump({**resume, "document": displayed}))
            )
        else:
            generate_docx(
                output,
                displayed,
                manifest_items,
                engine=engine,
                template_data=inputs.template_bytes,
                plan=template["mapping"]["plan"] if template else None,
                template_engine=template_engine,
            )
        if not output.is_file():
            raise Problem("文档引擎未生成声明的 DOCX 文件，未发布任何成品。", 409)
        pages, render_error = (
            renderer(output, directory / "resume.pdf")
            if renderer
            else (None, "Word 精确渲染未启用，DOCX 已生成。")
        )
        manifest = {
            "resume": resume,
            "template_id": template["id"] if template else None,
            "template_hash": template["hash"] if template else None,
            "layout": "adaptive-template" if template else "full-resume-v1",
            "items": manifest_items,
            "docx_hash": digest(output.read_bytes()),
            "renderer": (selected_renderer.identifier if selected_renderer else "Microsoft Word")
            if pages
            else None,
            "runtime": runtime,
            "engine": {"id": selected_engine.identifier, "version": selected_engine.value.version}
            if selected_engine
            else None,
            "rendering": {
                "id": selected_renderer.identifier,
                "version": selected_renderer.value.version,
            }
            if selected_renderer
            else None,
            "input_hash": digest(dump([resume, manifest_items, template]).encode()),
        }
        (directory / "manifest.json").write_text(dump(manifest), encoding="utf-8")
        resources = {}
        if self.assets:
            for path in sorted(directory.iterdir()):
                if path.name == "manifest.json" or path.name == "input-template.docx":
                    continue
                resources[path.name] = self.assets.stage(
                    "sys.documents",
                    path.read_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    if path.suffix == ".docx"
                    else "application/octet-stream",
                )
            manifest["assets"] = {name: row["id"] for name, row in resources.items()}
            (directory / "manifest.json").write_text(dump(manifest), encoding="utf-8")
        with self.db.transaction() as conn:
            if self.assets:
                self.assets.publish_bundle(conn, "sys.documents", f"exports/{export_id}", resources)
            conn.execute(
                "INSERT INTO exports VALUES (?,?,?,?,?,?)",
                (export_id, resume["id"], dump(manifest), pages, render_error, now()),
            )
        return self.db.one("SELECT * FROM exports WHERE id=?", (export_id,))
