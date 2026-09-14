"""完整简历的固定版本导出及可追溯清单。"""

from pathlib import Path

from resume_maker.core.errors import Problem, need
from resume_maker.domain.templates import TemplatePlan
from resume_maker.infrastructure.database import dump, now, uid
from resume_maker.integrations.sources import digest
from resume_maker.integrations.word.full_resume import write_full_resume
from resume_maker.integrations.word.rendering import render_word
from resume_maker.integrations.word.template_fill import fill_template
from resume_maker.services.catalog import Catalog


class Documents:
    """使用内置版式或完整模板，将固定版本简历导出为 Word。"""

    def __init__(self, catalog: Catalog, data_dir: Path):
        """保存当前模块所需依赖，供后续业务操作共享使用。"""
        self.catalog, self.db, self.data_dir = catalog, catalog.db, data_dir

    def export(self, resume_id: str) -> dict:
        """读取固定资料及项目引用，按所选完整模板或内置版式生成文件和清单。"""
        resume = need(
            self.db.one(
                "SELECT * FROM resumes WHERE id=? AND id NOT IN "
                "(SELECT resume_id FROM resume_deletions)",
                (resume_id,),
            ),
            "该简历方案不存在或已删除。",
        )
        template = self.catalog.template(resume["template_id"]) if resume["template_id"] else None
        if not resume["document"]:
            raise Problem("请先填写个人资料和栏目，再导出完整简历。")
        manifest_items = []
        for item in resume["items"]:
            revision = self.catalog.revision(item["revision_id"], item["project_id"])
            manifest_items.append(
                {
                    **item,
                    "revision_number": revision["number"],
                    "snapshot_id": revision["snapshot_id"],
                    "content": revision["content"],
                }
            )
        export_id = uid()
        directory = self.data_dir / "exports" / export_id
        directory.mkdir(parents=True)
        output = directory / "resume.docx"
        if template:
            source = self.data_dir / "templates" / template["id"] / "template.docx"
            if digest(source.read_bytes()) != template["hash"]:
                raise Problem("模板文件已在程序外变化，请重新导入。")
            fill_template(
                source,
                output,
                TemplatePlan.model_validate(template["mapping"]["plan"]),
                resume["document"],
                manifest_items,
            )
        else:
            write_full_resume(output, resume["document"], manifest_items)
        pages, render_error = render_word(output, directory / "resume.pdf")
        manifest = {
            "resume": resume,
            "template_id": template["id"] if template else None,
            "template_hash": template["hash"] if template else None,
            "layout": "adaptive-template" if template else "full-resume-v1",
            "items": manifest_items,
            "docx_hash": digest(output.read_bytes()),
            "renderer": "Microsoft Word" if pages else None,
        }
        (directory / "manifest.json").write_text(dump(manifest), encoding="utf-8")
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO exports VALUES (?,?,?,?,?,?)",
                (export_id, resume["id"], dump(manifest), pages, render_error, now()),
            )
        return self.db.one("SELECT * FROM exports WHERE id=?", (export_id,))
