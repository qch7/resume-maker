import json
import os
import subprocess
import sys
import threading
from copy import deepcopy
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import psutil
import pymupdf
from lxml import etree

from .catalog import Catalog, Problem, need
from .db import dump, now, uid
from .sources import digest

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
TAG = "resume-maker-projects"
RENDER_LOCK = threading.Lock()


def w(name: str) -> str:
    return f"{{{NS['w']}}}{name}"


def text_of(element) -> str:
    return "".join(element.xpath(".//w:t/text()", namespaces=NS))


def read_document(path: Path):
    try:
        with ZipFile(path) as archive:
            if sum(i.file_size for i in archive.infolist()) > 100_000_000:
                raise Problem("模板解压后过大，请使用小于 100 MB 的模板。")
            data = archive.read("word/document.xml")
            return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    except (BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
        raise Problem("文件不是有效的 Word DOCX 模板。") from exc


def inspect_template(path: Path) -> dict:
    root = read_document(path)
    body = root.find("w:body", NS)
    paragraphs = [
        {
            "index": i,
            "text": text_of(p)[:500],
            "has_section": bool(p.xpath(".//w:sectPr", namespaces=NS)),
        }
        for i, p in enumerate(body)
        if p.tag == w("p")
    ]
    start = end = None
    for row in paragraphs:
        if start is None and "项目经历" in row["text"]:
            start = row["index"] + 1
        elif (
            start is not None
            and row["index"] >= start
            and any(
                title in row["text"]
                for title in ("技能证书", "专业技能", "荣誉奖项", "教育背景", "自我评价")
            )
        ):
            end = row["index"]
            break
    if start is not None:
        while start < len(body) and not text_of(body[start]).strip():
            start += 1
    return {
        "paragraphs": paragraphs,
        "suggested_start": start,
        "suggested_end": end,
        "file_name": path.name,
    }


def rewrite_archive(source: Path, target: Path, root):
    xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    with ZipFile(source) as original, ZipFile(target, "w") as result:
        for item in original.infolist():
            result.writestr(
                item, xml if item.filename == "word/document.xml" else original.read(item)
            )


class Documents:
    def __init__(self, catalog: Catalog, data_dir: Path):
        self.catalog, self.db, self.data_dir = catalog, catalog.db, data_dir

    def import_template(self, path: Path, name: str, start: int, end: int) -> dict:
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
        resume = need(self.db.one("SELECT * FROM resumes WHERE id=?", (resume_id,)))
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
        # Keep section settings after the replacement region, not tied to deleted sample text.
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


def properties(paragraph):
    source = paragraph.find("w:pPr", NS)
    result = deepcopy(source) if source is not None else etree.Element(w("pPr"))
    for child in list(result):
        if child.tag in {w("sectPr"), w("pageBreakBefore"), w("keepNext"), w("keepLines")}:
            result.remove(child)
    return result


def set_property(properties, name, **attributes):
    item = properties.find(f"w:{name}", NS)
    if item is None:
        item = etree.SubElement(properties, w(name))
    for key, value in attributes.items():
        item.set(w(key), str(value))
    return item


def run(paragraph, text, bold=False):
    item = etree.SubElement(paragraph, w("r"))
    prop = etree.SubElement(item, w("rPr"))
    set_property(
        prop,
        "rFonts",
        ascii="Times New Roman",
        hAnsi="Times New Roman",
        eastAsia="微软雅黑" if bold else "宋体",
    )
    set_property(prop, "sz", val=24)
    set_property(prop, "color", val="343637")
    if bold:
        set_property(prop, "b")
    parts = text.split("\n")
    for index, part in enumerate(parts):
        if index:
            etree.SubElement(item, w("br"))
        node = etree.SubElement(item, w("t"))
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        node.text = part


def make_title(value, sample, first=False):
    paragraph = etree.Element(w("p"))
    prop = properties(sample)
    paragraph.append(prop)
    set_property(prop, "keepNext")
    set_property(prop, "widowControl")
    spacing = prop.find("w:spacing", NS)
    if not first or spacing is None:
        set_property(
            prop, "spacing", before=160 if not first else 0, after=60, line=280, lineRule="auto"
        )
    tabs = set_property(prop, "tabs")
    for tab in list(tabs):
        tabs.remove(tab)
    etree.SubElement(tabs, w("tab"), {w("val"): "right", w("pos"): "10200"})
    run(paragraph, value["title"], bold=True)
    if value["period"]:
        etree.SubElement(etree.SubElement(paragraph, w("r")), w("tab"))
        run(paragraph, value["period"], bold=True)
    return paragraph


def make_body(label, text, sample, keep=False):
    paragraph = etree.Element(w("p"))
    prop = properties(sample)
    paragraph.append(prop)
    set_property(prop, "spacing", before=30, after=20, line=285, lineRule="auto")
    set_property(prop, "widowControl")
    if keep:
        set_property(prop, "keepNext")
    run(paragraph, label + "：", bold=True)
    run(paragraph, text)
    return paragraph


def render_word(docx: Path, pdf: Path) -> tuple[int | None, str | None]:
    if os.name != "nt":
        return None, "本版本的精确预览需要 Windows 上的 Microsoft Word；DOCX 已生成。"
    with RENDER_LOCK:
        owner_file = pdf.with_suffix(".owner.json")
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "resume_maker.word_render",
                    str(docx),
                    str(pdf),
                    str(owner_file),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                creationflags=0x08000000,
            )
            if result.returncode or not pdf.exists():
                detail = result.stderr.strip().splitlines()
                return None, "Word 渲染失败，DOCX 仍可下载。" + (detail[-1][:300] if detail else "")
            with pymupdf.open(pdf) as document:
                for index, page in enumerate(document):
                    page.get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3)).save(
                        pdf.parent / f"page-{index + 1}.png"
                    )
                return len(document), None
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"Word 预览失败：{exc}"
        finally:
            if owner_file.exists():
                try:
                    owner = json.loads(owner_file.read_text())
                    process = psutil.Process(owner["pid"])
                    if (
                        process.create_time() == owner["created"]
                        and process.name().lower() == "winword.exe"
                    ):
                        process.kill()
                except (psutil.Error, OSError, ValueError):
                    pass
                owner_file.unlink(missing_ok=True)
