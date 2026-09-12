"""保留 DOCX 包结构的 XML 读取、区域识别与段落排版。"""

from copy import deepcopy
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from lxml import etree

from resume_maker.core.errors import Problem

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
TAG = "resume-maker-projects"


def w(name: str) -> str:
    """构造 WordprocessingML 命名空间中的完整 XML 标签名。"""
    return f"{{{NS['w']}}}{name}"


def text_of(element) -> str:
    """按文档顺序合并节点下的所有 Word 文本片段。"""
    return "".join(element.xpath(".//w:t/text()", namespaces=NS))


def read_document(path: Path):
    """校验 DOCX 包大小并禁用外部实体，安全读取正文 XML。"""
    try:
        with ZipFile(path) as archive:
            if sum(i.file_size for i in archive.infolist()) > 100_000_000:
                raise Problem("模板解压后过大，请使用小于 100 MB 的模板。")
            data = archive.read("word/document.xml")
            return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    except (BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
        raise Problem("文件不是有效的 Word DOCX 模板。") from exc


def inspect_template(path: Path) -> dict:
    """列出正文段落，并根据栏目标题建议项目经历替换区间。"""
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
    """仅替换正文 XML，逐项保留 DOCX 中其他文件及包元信息。"""
    xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    with ZipFile(source) as original, ZipFile(target, "w") as result:
        for item in original.infolist():
            result.writestr(
                item, xml if item.filename == "word/document.xml" else original.read(item)
            )


def properties(paragraph):
    """复制段落样式并移除分节、强制分页等不应随文本复用的属性。"""
    source = paragraph.find("w:pPr", NS)
    result = deepcopy(source) if source is not None else etree.Element(w("pPr"))
    for child in list(result):
        if child.tag in {w("sectPr"), w("pageBreakBefore"), w("keepNext"), w("keepLines")}:
            result.remove(child)
    return result


def set_property(properties, name, **attributes):
    """获取或创建指定 Word 样式节点，并写入对应属性。"""
    item = properties.find(f"w:{name}", NS)
    if item is None:
        item = etree.SubElement(properties, w(name))
    for key, value in attributes.items():
        item.set(w(key), str(value))
    return item


def run(paragraph, text, bold=False):
    """向段落追加指定字体的文本片段，保留空格并显式转换换行。"""
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
    """沿用标题样式创建项目名和右对齐日期，控制标题与后文连排。"""
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
    """沿用正文样式创建带加粗标签的段落，并按需与后文连排。"""
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
