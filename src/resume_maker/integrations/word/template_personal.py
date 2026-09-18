"""将个人资料的标签和值作为完整条目隐藏，并按原列数补齐空位。"""

import re
from collections import defaultdict
from copy import deepcopy

from lxml import etree

from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.template_map import can_insert, paragraph_text, quote_range

SEPARATORS = re.compile(r"[\t\n|｜;；]")
TEXT_TAGS = {w("t"), w("tab"), w("br"), w("cr")}


def paragraph_stream(paragraph):
    """保留制表位与换行的字符位置，同时建立原引文到可见行列的索引。"""
    text, positions = "", []
    for node in paragraph.iter():
        if next(node.iterancestors(w("p")), None) is not paragraph:
            continue
        if node.tag == w("t"):
            value = node.text or ""
            positions.extend(range(len(text), len(text) + len(value)))
            text += value
        elif node.tag in TEXT_TAGS:
            text += "\t" if node.tag == w("tab") else "\n"
    return text, positions


def slice_paragraph(paragraph, start, end):
    """按字符范围复制一条信息，保留标签、值各自的字体及超链接结构。"""
    clone, position = deepcopy(paragraph), 0
    for node in list(clone.iter()):
        if next(node.iterancestors(w("p")), None) is not clone or node.tag not in TEXT_TAGS:
            continue
        length = len(node.text or "") if node.tag == w("t") else 1
        if node.tag == w("t") and position < end and start < position + length:
            node.text = (node.text or "")[max(0, start - position) : end - position]
        else:
            node.getparent().remove(node)
        position += length
    # 片段重组后不复制原书签与修订身份，防止同一条信息出现多个 Word 锚点。
    for node in list(clone.iter(w("bookmarkStart"), w("bookmarkEnd"))):
        node.getparent().remove(node)
    return clone


def personal_items(paragraph, fields):
    """仅拆分边界明确的纯个人资料段落，混有标题、图片或复杂对象时保留原结构。"""
    if not fields or any(not field.target.startswith("personal.") for field in fields):
        return None
    if paragraph.xpath(
        ".//w:drawing | .//w:pict | .//w:object | .//w:fldChar | .//w:txbxContent "
        "| w:pPr/w:sectPr | .//w:br[@w:type='page' or @w:type='column']",
        namespaces=NS,
    ):
        return None
    stream, positions = paragraph_stream(paragraph)
    ranges = []
    for field in fields:
        start, end = quote_range(paragraph_text(paragraph), field)
        ranges.append(
            (
                positions[start] if start < len(positions) else 0,
                positions[end - 1] + 1 if end else 0,
                field,
            )
        )
    items, columns, row_count, begin = [], 1, 0, 0
    boundaries = [*SEPARATORS.finditer(stream)]
    spans = [
        (match.start(), match.end(), match.group())
        for match in boundaries
        if not any(start <= match.start() < end for start, end, _ in ranges)
    ]
    for end, following, separator in [*spans, (len(stream), len(stream), "\n")]:
        entries = [
            (start, stop, field) for start, stop, field in ranges if begin <= start and stop <= end
        ]
        if not stream[begin:end].strip() and not entries:
            begin = following
            continue
        if len(entries) != 1:
            return None
        start, stop, field = entries[0]
        prefix, suffix = stream[begin:start].strip(), stream[stop:end].strip()
        labelled = bool(re.fullmatch(r"[^:：]{1,50}[:：]\s*(?:GPA\s*)?", prefix, re.IGNORECASE))
        if prefix and not labelled:
            return None
        if suffix and not (field.target == "personal.age" and suffix in {"岁", "years old"}):
            return None
        fragment = slice_paragraph(paragraph, begin, end)
        prefix_length = len(stream[begin:start].replace("\t", "").replace("\n", ""))
        occurrence = (
            1
            + sum(
                match.start() < prefix_length
                for match in re.finditer(f"(?={re.escape(field.quote)})", paragraph_text(fragment))
            )
            if field.quote
            else 1
        )
        items.append((fragment, field.model_copy(update={"occurrence": occurrence}), row_count))
        row_count += 1
        columns = max(columns, row_count)
        if separator == "\n":
            row_count = 0
        begin = following
    if len(items) != len(fields):
        return None
    separator = "\t" if "\t" in stream.strip("\t") else " | "
    return items, columns, separator


def paragraph_style(paragraph):
    """按显式段落样式与列坐标分组，防止把页首姓名与联系方式混排。"""
    result = []
    for tag in ("pStyle", "ind", "tabs", "spacing", "jc", "framePr"):
        node = paragraph.find(f"w:pPr/w:{tag}", NS)
        if tag == "jc":
            result.append(node.get(w("val"), "left") if node is not None else "left")
            continue
        result.append(
            None
            if node is None
            else tuple((item.tag, tuple(sorted(item.attrib.items()))) for item in node.iter())
        )
    return tuple(result)


def append_separator(paragraph, value):
    """用原生制表符或换行连接条目，保留模板的列坐标和行距。"""
    run = etree.SubElement(paragraph, w("r"))
    if value in {"\t", "\n"}:
        etree.SubElement(run, w("tab" if value == "\t" else "br"))
    else:
        text = etree.SubElement(run, w("t"))
        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text.text = value


class PersonalLayout:
    """先保留完整个人条目片段，填值后只重排含隐藏或空条目的连续资料区域。"""

    def __init__(self, package, fields, values):
        """捕获原映射的行列和文字样式，生成独立填充片段而不修改已保存模板。"""
        self.nodes, self.fields, self.groups, self.tables = {}, [], [], []
        bindings = defaultdict(list)
        for field in fields:
            bindings[field.node].append(field)
        candidates = {}
        for identifier, paragraph in package.nodes.items():
            parsed = personal_items(paragraph, bindings.get(identifier, []))
            if parsed is not None:
                candidates[paragraph] = parsed
        visited = set()
        for table in package.nodes.values():
            if table.tag != w("tbl"):
                continue
            rows, items, columns = [], [], 0
            for row in [*table.findall(w("tr")), None]:
                parsed = table_row_items(row, candidates) if row is not None else None
                if rows and (parsed is None or len(row.findall(w("tc"))) != columns):
                    if any(not values.get(field.target) for _, field, _ in items):
                        self.tables.append((rows, self.add_fragments(items, values), columns))
                        visited.update(p for original in rows for p in original.iter(w("p")))
                    rows, items = [], []
                if parsed is not None:
                    columns = len(row.findall(w("tc")))
                    rows.append(row)
                    items.extend(parsed)
        for paragraph in candidates:
            if paragraph in visited:
                continue
            group, items = [], []
            columns, separator = 1, "\t"
            current = paragraph
            while (
                current in candidates
                and current not in visited
                and paragraph_style(current) == paragraph_style(paragraph)
            ):
                fragments, width, delimiter = candidates[current]
                visited.add(current)
                group.append(current)
                items.extend(fragments)
                if width > columns:
                    columns, separator = width, delimiter
                current = current.getnext()
            if all(values.get(field.target) for _, field, _ in items):
                continue
            self.groups.append((group, self.add_fragments(items, values), columns, separator))

    def add_fragments(self, items, values):
        """登记仍可见的条目，交给正式填充器替换以保留跨运行字体和链接处理。"""
        visible = []
        for fragment, field, column in items:
            if not values.get(field.target):
                continue
            identifier = f"personal-{len(self.nodes)}"
            self.nodes[identifier] = fragment
            self.fields.append(field.model_copy(update={"node": identifier}))
            visible.append((fragment, column))
        return visible

    def apply(self):
        """移除整条隐藏信息，后面的可见条目依原顺序补齐，整区为空时不留段落。"""
        for rows, visible, columns in self.tables:
            parent = rows[0].getparent()
            if parent is None:
                continue
            position = parent.index(rows[0])
            for offset, packed in enumerate(packed_rows(visible, columns)):
                clone = deepcopy(rows[min(offset, len(rows) - 1)])
                for index, cell in enumerate(clone.findall(w("tc"))):
                    for child in list(cell):
                        if child.tag != w("tcPr"):
                            cell.remove(child)
                    cell.append(
                        packed[index] if packed[index] is not None else etree.Element(w("p"))
                    )
                parent.insert(position, clone)
                position += 1
            for row in rows:
                parent.remove(row)
        for group, visible, columns, separator in self.groups:
            parent = group[0].getparent()
            if parent is None:
                continue
            position = parent.index(group[0])
            if columns == 1:
                replacements = [fragment for fragment, _ in visible]
            elif visible:
                paragraph = deepcopy(group[0])
                for child in list(paragraph):
                    if child.tag != w("pPr"):
                        paragraph.remove(child)
                for row_index, row in enumerate(packed_rows(visible, columns)):
                    if row_index:
                        append_separator(paragraph, "\n")
                    last = max(index for index, fragment in enumerate(row) if fragment is not None)
                    for column, fragment in enumerate(row[: last + 1]):
                        if column:
                            append_separator(paragraph, separator)
                        if fragment is not None:
                            for child in list(fragment):
                                if child.tag != w("pPr"):
                                    paragraph.append(child)
                replacements = [paragraph]
            else:
                replacements = []
            for node in group:
                if node.getparent() is parent:
                    parent.remove(node)
            for offset, node in enumerate(replacements):
                parent.insert(position + offset, node)
            if parent.tag == w("txbxContent") and not len(parent):
                etree.SubElement(parent, w("p"))


def table_row_items(row, candidates):
    """仅收紧每格都是个人条目的普通表格行，含照片、合并格或栏目标题时停止。"""
    if row.xpath(".//w:gridSpan | .//w:vMerge | .//w:tbl", namespaces=NS):
        return None
    items = []
    for column, cell in enumerate(row.findall(w("tc"))):
        for child in cell:
            if child.tag == w("tcPr"):
                continue
            if child in candidates:
                fragments, width, _ = candidates[child]
                if width > 1:
                    # 单元格自身已有多列时，由段落规则补位，不能压成表格的一列。
                    return None
                items.extend((fragment, field, column) for fragment, field, _ in fragments)
            elif not can_insert(child):
                return None
    return items or None


def packed_rows(visible, columns):
    """每列独立向上补位，保留右列坐标，避免把左列主页挪入狭窄的右列。"""
    grouped = [[] for _ in range(columns)]
    for fragment, column in visible:
        grouped[column].append(fragment)
    return [
        [column[index] if index < len(column) else None for column in grouped]
        for index in range(max(map(len, grouped), default=0))
    ]


def hidden_personal_range(text, target, start, end):
    """混合标题段落隐藏年龄时一并移除单位，不删固定标题与其他内容。"""
    if not target.startswith("personal."):
        return start, end
    if target == "personal.age":
        suffix = re.match(r"\s*(?:岁|years old)", text[end:])
        if suffix:
            end += suffix.end()
    return start, end
