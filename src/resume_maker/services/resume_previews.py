"""为未保存的当前资料生成临时 Word 模板预览，不发布草稿或登记导出。"""

import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from resume_maker.core.errors import Problem, need
from resume_maker.domain.templates import TemplatePlan
from resume_maker.infrastructure.database import dump, uid
from resume_maker.integrations.sources import digest
from resume_maker.integrations.word.full_resume import write_full_resume
from resume_maker.integrations.word.rendering import render_word
from resume_maker.integrations.word.template_fill import fill_template


class ResumePreviews:
    """串行渲染并复用相同输入，临时文件随应用实例回收。"""

    def __init__(self, catalog, data_dir):
        """仅保存依赖，首次预览时才创建临时目录。"""
        self.catalog, self.data_dir = catalog, data_dir
        self.lock = threading.Lock()
        self.directory = None
        self.results, self.cache = {}, {}
        self.stopped = False

    def render(self, template_id, document, items):
        """使用当前资料和可选经历工作副本试填，固定版本仅核验归属而不被修改。"""
        template = self.catalog.template(template_id) if template_id else None
        if document is None:
            raise Problem("请先填写个人资料和栏目。")
        data = None
        if template:
            source = self.data_dir / "templates" / template_id / "template.docx"
            data = source.read_bytes()
            if digest(data) != template["hash"]:
                raise Problem("模板文件已在程序外变化，请重新导入。")
        if len({item["project_id"] for item in items}) != len(items):
            raise Problem("项目引用不能重复。")
        projects = []
        for item in items:
            revision = self.catalog.revision(item["revision_id"], item["project_id"])
            content = item.get("content") or revision["content"]
            selected = item["highlight_ids"]
            valid = {point["id"] for point in content["highlights"]}
            if not set(selected) <= valid or len(selected) != len(set(selected)):
                raise Problem("预览引用了不存在或重复的亮点，请重新选择。")
            projects.append({**item, "content": content})
        key = digest(
            dump({"template": template, "document": document, "projects": projects}).encode()
        )
        with self.lock:
            if self.stopped:
                raise Problem("应用正在关闭。", 409)
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
            if template:
                snapshot = directory / "template.docx"
                snapshot.write_bytes(data)
                fill_template(
                    snapshot,
                    output,
                    TemplatePlan.model_validate(template["mapping"]["plan"]),
                    document,
                    projects,
                )
            else:
                write_full_resume(output, document, projects)
            pages, error = render_word(output, directory / "resume.pdf")
            result = {"id": identifier, "pages": pages, "render_error": error}
            self.results[identifier] = result
            if pages:
                self.cache[key] = result
            return dict(result)

    def file(self, identifier, filename):
        """只提供当前实例已生成的预览文件，模板源文件和任意路径均不可下载。"""
        # 读已发布结果不占用渲染锁，更新下一版时上一版图片仍能立即加载。
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
        """请求结束后回收本实例创建的预览目录，正式简历和导出文件不受影响。"""
        with self.lock:
            self.stopped = True
            self.results.clear()
            self.cache.clear()
            if self.directory:
                self.directory.cleanup()
