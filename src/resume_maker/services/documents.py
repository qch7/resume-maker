"""模板登记、固定版本组合导出及可追溯清单的业务编排。"""

from pathlib import Path

from lxml import etree

from resume_maker.core.errors import Problem, need
from resume_maker.domain.templates import TemplatePlan
from resume_maker.infrastructure.database import dump, now, uid
from resume_maker.integrations.sources import digest
from resume_maker.integrations.word.full_resume import write_full_resume
from resume_maker.integrations.word.ooxml import (
    NS,
    TAG,
    read_document,
    rewrite_archive,
    w,
)
from resume_maker.integrations.word.project_template import fill_project_template
from resume_maker.integrations.word.rendering import render_word
from resume_maker.integrations.word.template_fill import fill_template
from resume_maker.services.catalog import Catalog


class Documents:
    """登记模板并把固定版本组合导出为可编辑 Word 文档。"""

    def __init__(self, catalog: Catalog, data_dir: Path):
        """保存当前模块所需依赖，供后续业务操作共享使用。"""
        self.catalog, self.db, self.data_dir = catalog, catalog.db, data_dir

    def import_template(self, path: Path, name: str, start: int, end: int) -> dict:
        """复制原模板并标记项目经历区域，登记模板哈希和区间映射。"""
        path = path.expanduser().resolve(strict=True)
        root = read_document(path)
        body = root.find("w:body", NS)
        if not 0 <= start < end < len(body):
            raise Problem("替换区域无效：起点须在终点之前，终点为下一个保留段落。")
        selected = list(body)[start:end]
        if any(node.tag != w("p") for node in selected):
            raise Problem("当前模板适配要求项目经历区域由正文段落组成。")
        template_id = uid()
        directory = self.data_dir / "templates" / template_id
        directory.mkdir(parents=True)
        source = directory / "original.docx"
        source.write_bytes(path.read_bytes())
        sdt = etree.Element(w("sdt"))
        properties = etree.SubElement(sdt, w("sdtPr"))
        etree.SubElement(properties, w("tag")).set(w("val"), TAG)
        content = etree.SubElement(sdt, w("sdtContent"))
        for node in selected:
            body.remove(node)
            content.append(node)
        body.insert(start, sdt)
        managed = directory / "template.docx"
        rewrite_archive(source, managed, root)
        mapping = {
            "start": start,
            "end": end,
            "source_name": path.name,
            "section_count": len(sdt.xpath(".//w:sectPr", namespaces=NS)),
        }
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO templates VALUES (?,?,?,?,?)",
                (
                    template_id,
                    name.strip() or path.stem,
                    digest(managed.read_bytes()),
                    dump(mapping),
                    now(),
                ),
            )
        return self.db.one("SELECT * FROM templates WHERE id=?", (template_id,))

    def export(self, resume_id: str) -> dict:
        """读取固定版本组合，替换模板经历区并保存 DOCX、预览和追溯清单。"""
        resume = need(
            self.db.one(
                "SELECT * FROM resumes WHERE id=? AND id NOT IN "
                "(SELECT resume_id FROM resume_deletions)",
                (resume_id,),
            ),
            "该简历方案不存在或已删除。",
        )
        if resume["document"] and not resume["template_id"]:
            return self.export_full(resume)
        template = need(
            self.db.one("SELECT * FROM templates WHERE id=?", (resume["template_id"],)),
            "请先选择 Word 模板。",
        )
        if "plan" in template["mapping"]:
            return self.export_full(resume, template)
        if not resume["items"]:
            raise Problem("请至少选择一个项目经历。")
        source = self.data_dir / "templates" / template["id"] / "template.docx"
        if digest(source.read_bytes()) != template["hash"]:
            raise Problem("模板文件已在程序外变化，请重新导入为新模板版本。")
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
        fill_project_template(source, output, manifest_items)
        pages, render_error = render_word(output, directory / "resume.pdf")
        manifest = {
            "resume": resume,
            "template_id": template["id"],
            "template_hash": template["hash"],
            "items": manifest_items,
            "docx_hash": digest(output.read_bytes()),
            "renderer": "Microsoft Word" if pages else None,
        }
        (directory / "manifest.json").write_text(dump(manifest), encoding="utf-8")
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO exports VALUES (?,?,?,?,?,?)",
                (export_id, resume_id, dump(manifest), pages, render_error, now()),
            )
        return self.db.one("SELECT * FROM exports WHERE id=?", (export_id,))

    def export_full(self, resume: dict, template: dict | None = None) -> dict:
        """导出完整简历并记录个人信息、栏目结构、固定项目版本及真实渲染结果。"""
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
