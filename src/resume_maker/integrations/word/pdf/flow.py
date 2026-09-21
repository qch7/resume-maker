"""借助版面解析器生成可编辑文字流；局部捕获段落几何而不修改全局 Word 行为"""

import re
import unicodedata
from collections import Counter
from copy import deepcopy
from io import BytesIO

import pymupdf
from docx.oxml.ns import qn
from docx.shared import Pt

from resume_maker.core.errors import Problem
from resume_maker.integrations.word.pdf.columns import parse_sidebar
from resume_maker.integrations.word.pdf.geometry import SOURCE, mark_paragraph


def text_counter(text):
    """按非空白字符统计原文覆盖以免布局转换静默漏字或漏掉整个栏目"""
    return Counter(char for char in unicodedata.normalize("NFKC", text) if not char.isspace())


def text_blocks(blocks):
    """遍历正文及嵌套表格中的文字块；保持解析器的容器结构"""
    for block in blocks:
        if block.is_text_block:
            yield block
        elif block.is_table_block:
            for row in block:
                for cell in row:
                    if cell:
                        yield from text_blocks(cell.blocks)


def font_family(name):
    """去除 PDF 子集和字体样式后缀以免把错误的子集族名当作系统字体"""
    name = re.sub(r"^[A-Z]{6}\+", "", name)
    return re.sub(
        r"[ -](?:Thin|ExtraLight|Light|Regular|Medium|SemiBold|Bold|Black|Italic|Oblique)$",
        "",
        name,
        flags=re.IGNORECASE,
    )


def merge_bullet_table(block, column_left):
    """将误识别为两列表格的列表还原为文字块以免多行正文与符号各自排版后错位"""
    from pdf2docx.text.TextBlock import TextBlock

    if not block.is_stream_table_block or block.num_cols != 2:
        return block
    lines = []
    for row in block:
        marker, content = row[0], row[1]
        if not marker or not content:
            return block
        if not all(
            item.is_text_block and item.is_horizontal_text for cell in row for item in cell.blocks
        ):
            return block
        marker_text = "".join(item.text for item in marker.blocks).strip()
        if not marker_text or set(marker_text) - {"•", " ", "\n"}:
            return block
        for cell in row:
            for item in cell.blocks:
                for line in item.lines:
                    raw = line.store()
                    if cell is marker:
                        raw["line_break"] = 0
                    lines.append(raw)
    lines.sort(key=lambda line: (line["bbox"][1], line["bbox"][0]))
    merged = TextBlock({"lines": lines})
    merged.before_space = block.before_space + max(0, merged.bbox.y0 - block.bbox.y0)
    merged.after_space = block.after_space
    merged.left_space = merged.bbox.x0 - column_left
    return merged


def separate_blocks(blocks, column_left, *, split_lines=False):
    """大间隔、颜色变化和列表首行建立段落边界以免标题与条目被合并后无法单独排序"""
    from pdf2docx.text.TextBlock import TextBlock

    output = []
    for block in blocks:
        block = merge_bullet_table(block, column_left)
        if block.is_table_block:
            for row in block:
                for cell in row:
                    if cell:
                        separate_blocks(
                            cell.blocks,
                            cell.bbox.x0,
                            split_lines=split_lines or getattr(block, "independent_columns", False),
                        )
        if not block.is_text_block or not block.is_horizontal_text:
            output.append(block)
            continue
        groups, previous, color = [], None, None
        for row in block.lines.group_by_physical_rows():
            row.sort_in_line_order()
            spans = [span for line in row for span in line.spans if span.text.strip()]
            current_color = max(spans, key=lambda span: len(span.text)).color if spans else color
            new = (
                previous is None
                or split_lines
                or row[0].text.lstrip().startswith("•")
                or current_color != color
                or row.bbox.y0 - previous.bbox.y1 > max(row.bbox.height, previous.bbox.height) * 0.7
            )
            if new:
                groups.append([])
            groups[-1].extend(row)
            previous, color = row, current_color
        if len(groups) < 2:
            output.append(block)
            continue
        previous_bottom = None
        for index, lines in enumerate(groups):
            data = block.store()
            data["lines"] = [line.store() for line in lines]
            chunk = TextBlock(data)
            chunk.before_space = (
                block.before_space
                if previous_bottom is None
                else max(0, chunk.bbox.y0 - previous_bottom)
            )
            chunk.after_space = block.after_space if index == len(groups) - 1 else 0
            chunk.left_space += chunk.bbox.x0 - block.bbox.x0
            # 原块的制表位相对旧起点；拆段后重算以免左缩进与旧制表位叠加挤窄正文
            for line in chunk.lines:
                line.tab_stop = 0
            chunk.lines.parse_tab_stop(5.0)
            for line in chunk.lines.group_by_physical_rows()[-1]:
                line.line_break = 0
            output.append(chunk)
            previous_bottom = chunk.bbox.y1
    blocks.reset(output)


def repair_hyperlinks(paragraph):
    """规范转换器生成的嵌套超链接；把格式移到实际文字运行；保留可编辑的合法 OOXML"""
    for link in list(paragraph._p.iter(qn("w:hyperlink"))):
        run = link.getparent()
        if run.tag != qn("w:r"):
            continue
        style = run.find(qn("w:rPr"))
        if style is not None:
            for child in link.findall(qn("w:r")):
                old = child.find(qn("w:rPr"))
                if old is not None:
                    child.remove(old)
                child.insert(0, deepcopy(style))
        run.addprevious(link)
        if all(child.tag == qn("w:rPr") for child in run):
            run.getparent().remove(run)


def capture_block(block, captured, column_left):
    """只包装当前解析块的输出；记录它生成的段落和源坐标且不猴子补丁全局类"""
    for line in block.lines:
        for span in line.spans:
            span.font = "Arial" if span.text == "•" else font_family(span.font)
    block.line_space_type = 0
    block.parse_exact_line_spacing()
    original = block.make_docx

    def make(paragraph):
        """保留原字号的行距并用悬挂缩进和制表符维持列表符号与正文间距"""
        original(paragraph)
        repair_hyperlinks(paragraph)
        align_bullet(paragraph, block, column_left)
        mark_paragraph(paragraph._p, block)
        captured.append((paragraph, pymupdf.Rect(block.bbox), column_left))

    block.make_docx = make


def align_bullet(paragraph, block, column_left):
    """只处理有真实符号位置的列表首行；续行按原正文起点对齐"""
    if not paragraph.text.startswith("•"):
        return
    spans = [span for line in block.lines for span in line.spans]
    marker = next((s for s in spans if s.text == "•"), None)
    if marker is None:
        return
    following = [
        s
        for s in spans
        if s.bbox.x0 > marker.bbox.x1 and abs(s.bbox.y1 - marker.bbox.y1) < marker.size / 2
    ]
    if not following:
        return
    left = min(s.bbox.x0 for s in following)
    style = paragraph.paragraph_format
    style.left_indent = Pt(left - column_left)
    style.first_line_indent = Pt(marker.bbox.x0 - left)
    style.tab_stops.add_tab_stop(Pt(left - column_left))
    run = next((run for run in paragraph.runs if run.text), None)
    if run is not None and run.text.startswith("•") and not run.text.startswith("•\t"):
        run.text = "•\t" + run.text[1:]


def convert_flow(page, bullets=(), symbols=(), *, split_lines=True):
    """在去图的 PDF 副本中保留物理行边界，防止多个样本被合成无法重复的单段"""
    # 延迟导入；普通 DOCX 识别不加载 PDF 转换器；也不受其字体和日志初始化影响
    from docx import Document
    from pdf2docx import Converter

    with pymupdf.open(stream=page.parent.tobytes(), filetype="pdf") as text_pdf:
        clean = text_pdf[page.number]
        links = clean.get_links()
        clean.add_redact_annot(clean.rect, fill=None)
        clean.apply_redactions(images=1, graphics=2, text=1)
        for box, _ in symbols:
            clean.add_redact_annot(box, fill=None)
        if symbols:
            clean.apply_redactions(images=0, graphics=0, text=0)
        # Redaction 会移除相交链接；即使选择保留文字；恢复原 URI 关系供后续字段替换处理
        for link in links:
            if link["kind"] == pymupdf.LINK_URI:
                clean.insert_link(
                    {"kind": pymupdf.LINK_URI, "from": link["from"], "uri": link["uri"]}
                )
        if bullets:
            font = pymupdf.Font("cjk")
            clean.insert_font(fontname="RecoveredBullet", fontbuffer=font.buffer)
            for center, baseline, size in bullets:
                width = font.text_length("•", fontsize=size)
                clean.insert_text(
                    (center - width / 2, baseline), "•", fontsize=size, fontname="RecoveredBullet"
                )
        converter = Converter(stream=text_pdf.tobytes())
    try:
        settings = {
            **converter.default_settings,
            "ignore_page_error": False,
            "raw_exceptions": True,
            "multi_processing": False,
        }
        converter.load_pages(pages=[page.number]).parse_document(**settings)
        layout = converter.pages[page.number]
        captured = []
        for section in layout.sections:
            for column in section:
                if not parse_sidebar(column, page, settings):
                    column.parse(**settings)
                separate_blocks(column.blocks, column.bbox.x0, split_lines=split_lines)
                for block in text_blocks(column.blocks):
                    capture_block(block, captured, column.bbox.x0)
        document = Document()
        document._element.set(SOURCE, "1")
        layout.make_docx(document)
        for row in document._element.iter(qn("w:trHeight")):
            row.set(qn("w:hRule"), "atLeast")
        expected = text_counter(page.get_text())
        expected.subtract(text_counter("".join(text for _, text in symbols)))
        expected = +expected
        actual = text_counter("".join(p.text for p, _, _ in captured))
        missing = expected - actual
        if not captured or missing:
            raise Problem("PDF 版面转换未完整保留原文，已转入逐页视觉恢复。")
        return document, captured
    finally:
        converter.close()


def append_document(target, source):
    """合并本次生成的单页文档；重建图片关系并保留各页分节、表格和页边距"""
    from docx.enum.section import WD_SECTION_START
    from docx.opc.constants import RELATIONSHIP_TYPE as RT

    body = target._element.body
    if source._element.get(SOURCE) == "1":
        target._element.set(SOURCE, "1")
    if len(body) > 1:
        target.add_section(WD_SECTION_START.NEW_PAGE)
    relationships = {}
    for rel in source.part.rels.values():
        if rel.reltype == RT.IMAGE:
            identifier, _ = target.part.get_or_add_image(BytesIO(rel.target_part.blob))
            relationships[rel.rId] = identifier
        elif rel.reltype == RT.HYPERLINK and rel.is_external:
            relationships[rel.rId] = target.part.relate_to(rel.target_ref, RT.HYPERLINK, True)
    for node in source._element.body:
        clone = deepcopy(node)
        for item in clone.iter():
            for key in (qn("r:embed"), qn("r:id")):
                value = item.get(key)
                if value in relationships:
                    item.set(key, relationships[value])
        if node.tag == qn("w:sectPr"):
            body.remove(body.sectPr)
            body.append(clone)
        else:
            body.insert(len(body) - 1, clone)
    # 图片在不同 PDF 页中可能使用同一个绘图编号；合并后重新编号以兼容 Word
    for number, item in enumerate(target._element.iter(qn("wp:docPr")), 1):
        item.set("id", str(number))
