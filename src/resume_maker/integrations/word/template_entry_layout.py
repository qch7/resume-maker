"""根据条目的有效样式和排版容器统一文字起点，不依赖模板名称或固定坐标。"""

from collections import Counter, defaultdict
from copy import deepcopy

from lxml import etree

from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.template_flow import effective_section

METADATA = {"title", "subtitle", "period"}
BODY_FIELDS = {"details", "description", "highlights", "stack", "role", "custom_fields"}


def merge_properties(target, source):
    """逐属性展开继承的格式，保留字体及其他属性，不把缺省值当成覆盖。"""
    target.attrib.update(source.attrib)
    for child in source:
        existing = (
            next(
                (
                    node
                    for node in target
                    if node.tag == child.tag and node.get(w("pos")) == child.get(w("pos"))
                ),
                None,
            )
            if child.tag == w("tab")
            else target.find(child.tag)
        )
        if existing is None:
            target.append(deepcopy(child))
        else:
            merge_properties(existing, child)


class ParagraphStyles:
    """解析默认样式、继承链和编号级别，取得 Word 实际使用的段落几何属性。"""

    def __init__(self, package):
        """只读取样式部件，填充时不修改源样式或全局编号定义。"""
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        source = package.files.get("word/styles.xml")
        styles = etree.fromstring(source, parser) if source else etree.Element(w("styles"))
        self.styles = {node.get(w("styleId")): node for node in styles.findall(w("style"))}
        self.default = next(
            (
                key
                for key, node in self.styles.items()
                if node.get(w("type")) == "paragraph" and node.get(w("default")) == "1"
            ),
            None,
        )
        self.defaults = styles.find("w:docDefaults/w:pPrDefault/w:pPr", NS)
        self.numbering = (
            etree.fromstring(package.files["word/numbering.xml"], parser)
            if "word/numbering.xml" in package.files
            else None
        )
        self.cache = {}
        self.package, self.root, self.flat = package, styles, {}

    def isolate_indent(self, paragraph, indent):
        """字符缩进不能靠删除直接属性取消；为冲突样式生成独立展开副本，保留字体与原样式。"""
        reference = paragraph.find("w:pPr/w:pStyle", NS)
        identifier = reference.get(w("val")) if reference is not None else self.default
        inherited = {}
        for properties in self.chain(identifier):
            node = properties.find(w("ind"))
            if node is not None:
                inherited.update(node.attrib)
        conflicts = ("leftChars", "startChars", "start")
        if not any(w(key) in inherited and w(key) not in indent for key in conflicts):
            return
        if identifier not in self.flat:
            key = f"resume-layout-{len(self.flat) + 1}"
            while key in self.styles:
                key += "-copy"
            style = etree.Element(w("style"), {w("type"): "paragraph", w("styleId"): key})
            etree.SubElement(style, w("name")).set(w("val"), key)
            properties = etree.SubElement(style, w("pPr"))
            for source in self.chain(identifier):
                merge_properties(properties, source)
            inherited_indent = properties.find(w("ind"))
            if inherited_indent is not None:
                for name in conflicts:
                    inherited_indent.attrib.pop(w(name), None)
            fonts = etree.SubElement(style, w("rPr"))
            defaults = self.root.find("w:docDefaults/w:rPrDefault/w:rPr", NS)
            if defaults is not None:
                merge_properties(fonts, defaults)
            chain, visited, current = [], set(), identifier
            while current in self.styles and current not in visited:
                visited.add(current)
                source = self.styles[current]
                chain.insert(0, source)
                parent = source.find(w("basedOn"))
                current = parent.get(w("val")) if parent is not None else None
            for source in chain:
                run = source.find(w("rPr"))
                if run is not None:
                    merge_properties(fonts, run)
            self.root.append(style)
            self.styles[key] = style
            self.flat[identifier] = key
            self.package.files["word/styles.xml"] = etree.tostring(
                self.root, xml_declaration=True, encoding="UTF-8"
            )
        if reference is None:
            properties = paragraph.find(w("pPr"))
            if properties is None:
                properties = etree.Element(w("pPr"))
                paragraph.insert(0, properties)
            reference = etree.Element(w("pStyle"))
            properties.insert(0, reference)
        reference.set(w("val"), self.flat[identifier])

    def chain(self, identifier):
        """按父样式到子样式展开属性，循环或失效引用不会无限递归。"""
        if identifier not in self.cache:
            chain, visited = [], set()
            while identifier in self.styles and identifier not in visited:
                visited.add(identifier)
                style = self.styles[identifier]
                chain.insert(0, style.find(w("pPr")))
                parent = style.find(w("basedOn"))
                identifier = parent.get(w("val")) if parent is not None else None
            result = [node for node in [self.defaults, *chain] if node is not None]
            return result
        return self.cache[identifier]

    def properties(self, paragraph):
        """显式段落属性优先于继承样式，没有样式引用时使用默认段落样式。"""
        reference = paragraph.find("w:pPr/w:pStyle", NS)
        identifier = reference.get(w("val")) if reference is not None else self.default
        if identifier not in self.cache:
            self.cache[identifier] = self.chain(identifier)
        own = paragraph.find(w("pPr"))
        return [*self.cache[identifier], *([own] if own is not None else [])]

    def attributes(self, paragraph, path):
        """按属性合并缩进和开关，支持子样式只覆盖父样式的部分属性。"""
        result = {}
        for properties in self.properties(paragraph):
            node = properties.find(path, NS)
            if node is not None:
                result.update(node.attrib)
        return result

    def numbered(self, paragraph):
        """编号来自段落或样式均算列表，显式 numId=0 则禁用继承编号。"""
        return self.attributes(paragraph, "w:numPr/w:numId").get(w("val"), "0") != "0"

    def indent(self, paragraph):
        """读取文字左侧基准，编号级别提供默认缩进，段落显式属性具有最高优先级。"""
        result = self.attributes(paragraph, "w:ind")
        if self.numbered(paragraph) and self.numbering is not None:
            number = self.attributes(paragraph, "w:numPr/w:numId")[w("val")]
            level = self.attributes(paragraph, "w:numPr/w:ilvl").get(w("val"), "0")
            instance = self.numbering.find(f"w:num[@w:numId='{number}']", NS)
            if instance is not None:
                override = instance.find(f"w:lvlOverride[@w:ilvl='{level}']/w:lvl/w:pPr/w:ind", NS)
                reference = instance.find(w("abstractNumId"))
                if override is None and reference is not None:
                    identifier = reference.get(w("val"))
                    override = self.numbering.find(
                        f"w:abstractNum[@w:abstractNumId='{identifier}']/w:lvl[@w:ilvl='{level}']/w:pPr/w:ind",
                        NS,
                    )
                if override is not None:
                    result.update(override.attrib)
            own = paragraph.find("w:pPr/w:ind", NS)
            if own is not None:
                result.update(own.attrib)
        # 只统一本列的左侧基准；右侧日期制表位、段落右缩进和文字样式独立保留。
        keys = ("left", "start", "leftChars", "startChars")
        return {w(key): result[w(key)] for key in keys if w(key) in result} or {w("left"): "0"}

    def group(self, paragraph):
        """只对同一容器和同一单栏节的左对齐文字归组，保留多栏、右对齐及固定文本框设计。"""
        alignment = self.attributes(paragraph, "w:jc").get(w("val"), "left")
        if alignment not in {"left", "start", "both", "distribute"}:
            return None
        if any(
            properties.find(w("framePr")) is not None for properties in self.properties(paragraph)
        ):
            return None
        bidi = [properties.find(w("bidi")) for properties in self.properties(paragraph)]
        bidi = [node for node in bidi if node is not None]
        if bidi and bidi[-1].get(w("val"), "1") not in {"0", "false", "off"}:
            return None
        section = effective_section(paragraph)
        columns = section.find(w("cols")) if section is not None else None
        if columns is not None and (
            int(columns.get(w("num"), "1")) > 1 or len(columns.findall(w("col"))) > 1
        ):
            return None
        return paragraph.getparent(), section


def common_indent(styles, nodes, fields):
    """优先选择正文里最常见的左侧基准，仅有列表时沿用列表文字的起点。"""
    targets = defaultdict(set)
    for field in fields:
        targets[nodes[field.node]].add(field.target)
    paragraphs = [node for node in targets if styles.group(node) is not None]
    body = [node for node in paragraphs if targets[node] & BODY_FIELDS]
    plain = [node for node in body if not styles.numbered(node)]
    candidates = (
        plain or body or [node for node in paragraphs if "title" in targets[node]] or paragraphs
    )
    if not candidates:
        return {w("left"): "0"}
    coordinates = [tuple(sorted(styles.indent(node).items())) for node in candidates]
    return dict(Counter(coordinates).most_common(1)[0][0])


def apply_indent(paragraph, indent, unnumbered=False):
    """显式覆盖可能继承的首行、悬挂及字符缩进，使文字起点一致而保留右侧排版。"""
    properties = paragraph.find(w("pPr"))
    if properties is None:
        properties = etree.Element(w("pPr"))
        paragraph.insert(0, properties)
    node = properties.find(w("ind"))
    if node is None:
        node = etree.SubElement(properties, w("ind"))
    for key in (
        "left",
        "start",
        "leftChars",
        "startChars",
        "firstLine",
        "hanging",
        "firstLineChars",
        "hangingChars",
    ):
        node.attrib.pop(w(key), None)
    node.set(w("left"), indent.get(w("left"), "0"))
    for key in ("firstLine", "hanging", "firstLineChars", "hangingChars"):
        node.set(w(key), "0")
    node.attrib.update(indent)
    if unnumbered:
        number = properties.find(w("numPr"))
        if number is not None:
            properties.remove(number)
        number = etree.SubElement(properties, w("numPr"))
        etree.SubElement(number, w("numId")).set(w("val"), "0")


def align_record(styles, nodes, fields):
    """每条记录分别校准标题和元信息，列表层级、正文缩进及跨列布局保持原样。"""
    groups, targets = defaultdict(list), defaultdict(set)
    for field in fields:
        node = nodes[field.node]
        targets[node].add(field.target)
        group = styles.group(node)
        if group is not None:
            groups[group].append(field)
    for fields in groups.values():
        paragraphs = {nodes[field.node] for field in fields}
        if len(paragraphs) < 2:
            continue
        indent = common_indent(styles, nodes, fields)
        for node in paragraphs:
            if targets[node] <= METADATA and not styles.numbered(node):
                styles.isolate_indent(node, indent)
                apply_indent(node, indent)
