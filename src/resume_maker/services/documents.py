"""模板登记、固定版本组合导出及可追溯清单的业务编排。"""

from copy import deepcopy
from pathlib import Path

from lxml import etree

from resume_maker.core.errors import Problem, need
from resume_maker.infrastructure.database import dump, now, uid
from resume_maker.integrations.sources import digest
from resume_maker.integrations.word.full_resume import write_full_resume
from resume_maker.integrations.word.ooxml import (
    NS,
    TAG,
    make_body,
    make_title,
    read_document,
    rewrite_archive,
    text_of,
    w,
)
from resume_maker.integrations.word.rendering import render_word
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
        if not resume["items"]:
            raise Problem("请至少选择一个项目经历。")
        source = self.data_dir / "templates" / template["id"] / "template.docx"
        if digest(source.read_bytes()) != template["hash"]:
            raise Problem("模板文件已在程序外变化，请重新导入为新模板版本。")
        root = read_document(source)
        controls = root.xpath("//w:sdt[w:sdtPr/w:tag[@w:val=$tag]]", namespaces=NS, tag=TAG)
        if len(controls) != 1:
            raise Problem("模板缺少唯一项目经历插入位置，请重新导入。")
        content = controls[0].find("w:sdtContent", NS)
        old = list(content)
        title_sample = next((p for p in old if text_of(p).strip()), old[0])
        body_sample = next((p for p in old if "项目描述" in text_of(p)), title_sample)
        sections = [deepcopy(s) for s in content.xpath(".//w:sectPr", namespaces=NS)]
        for child in list(content):
            content.remove(child)
        manifest_items = []
        for index, item in enumerate(resume["items"]):
            revision = self.catalog.revision(item["revision_id"], item["project_id"])
            value = revision["content"]
            content.append(make_title(value, title_sample, first=index == 0))
            if value["stack"]:
                content.append(
                    make_body("技术栈", "、".join(value["stack"]), body_sample, keep=True)
                )
            if value["role"]:
                content.append(make_body("担任角色", value["role"], body_sample, keep=True))
            if value["description"]:
                content.append(make_body("项目描述", value["description"], body_sample, keep=True))
            by_id = {h["id"]: h for h in value["highlights"]}
            for point_id in item["highlight_ids"]:
                if point_id not in by_id:
                    raise Problem("组合引用了无效亮点，请重新保存组合。")
                highlight = by_id[point_id]
                content.append(make_body(highlight["title"], highlight["text"], body_sample))
            manifest_items.append(
                {
                    **item,
                    "revision_number": revision["number"],
                    "snapshot_id": revision["snapshot_id"],
                    "content": value,
                }
            )
        # 把分节设置保留在替换区域末尾，避免删除示例正文时丢失页眉页脚等设置。
        for section in sections:
            paragraph = etree.SubElement(content, w("p"))
            etree.SubElement(paragraph, w("pPr")).append(section)
        export_id = uid()
        directory = self.data_dir / "exports" / export_id
        directory.mkdir(parents=True)
        output = directory / "resume.docx"
        rewrite_archive(source, output, root)
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

    def export_full(self, resume: dict) -> dict:
        """导出完整简历并记录个人信息、栏目结构、固定项目版本及真实渲染结果。"""
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
        write_full_resume(output, resume["document"], manifest_items)
        pages, render_error = render_word(output, directory / "resume.pdf")
        manifest = {
            "resume": resume,
            "template_id": None,
            "layout": "full-resume-v1",
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
