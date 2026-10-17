"""按文档结构释放分页限制，保留文本、图片、复杂表格及不同页面的节配置"""

from lxml import etree

from resume_maker.integrations.word.ooxml import NS, w


def property_node(parent, name):
    """仅补足指定属性，段落属性保持在内容之前"""
    node = parent.find(w(name))
    if node is None:
        node = etree.Element(w(name))
        parent.insert(0, node) if name == "pPr" else parent.append(node)
    return node


def enabled(node):
    """解释 Word 开关的省略值及明确关闭值"""
    return node is not None and node.get(w("val"), "1") not in {"0", "false", "off"}


def paragraph_flag(paragraph, definitions, name, visited=None):
    """取得直接设置或样式继承的分页开关，明确关闭不再向上继承"""
    direct = paragraph.find(f"w:pPr/w:{name}", NS)
    if direct is not None:
        return enabled(direct)
    style = paragraph.find("w:pPr/w:pStyle", NS)
    identifier = style.get(w("val")) if style is not None else "Normal"
    visited = set() if visited is None else visited
    while identifier in definitions and identifier not in visited:
        visited.add(identifier)
        definition = definitions[identifier]
        value = definition.find(f"w:pPr/w:{name}", NS)
        if value is not None:
            return enabled(value)
        parent = definition.find(w("basedOn"))
        identifier = parent.get(w("val")) if parent is not None else None
    return False


def text_only(node):
    """图形、域、合并单元格或嵌套表格不能按普通文本容器压缩"""
    return not node.xpath(
        ".//w:drawing | .//w:pict | .//w:object | .//w:fldChar | .//w:instrText "
        "| .//w:gridSpan | .//w:vMerge | .//w:tbl | .//w:framePr | .//w:txbxContent",
        namespaces=NS,
    )


def positioned_content(root):
    """浮动对象可能依赖邻段留白及页边界，压缩前需确定可独立回流的区域"""
    return bool(root.xpath(".//*[local-name()='anchor'] | .//w:pict | .//w:framePr", namespaces=NS))


def top_positioned_boundary(root):
    """识别按页面顶边固定的绘图边界，其前文字及让位区域继续保护"""
    body = root.find(w("body"))
    if body is None:
        return None
    boundary = None
    for block in body:
        if not positioned_content(block):
            continue
        if block.tag != w("p") or block.xpath(".//w:pict | .//w:framePr", namespaces=NS):
            return None
        anchors = block.xpath(".//*[local-name()='anchor']")
        for anchor in anchors:
            vertical = anchor.find("{*}positionV")
            offset = vertical.find("{*}posOffset") if vertical is not None else None
            if (
                vertical is None
                or vertical.get("relativeFrom") != "page"
                or offset is None
                or int(offset.text or "0") != 0
            ):
                return None
        boundary = block
    return boundary


def flow_blocks(root):
    """页顶图形之前及其后连续留白保持原样，仅后续自然流区域参与分页释放"""
    if not positioned_content(root):
        return [root]
    boundary = top_positioned_boundary(root)
    if boundary is None:
        return []
    blocks = []
    block = boundary.getnext()
    while block is not None:
        if blocks or block.xpath(
            ".//w:t[normalize-space()] | .//*[local-name()='inline']", namespaces=NS
        ):
            blocks.append(block)
        block = block.getnext()
    return blocks


def release_chain(chain):
    """长相邻链仅保留短首段跟随下一段，正文不再整组被推到新页"""
    for index, paragraph in enumerate(chain):
        text = "".join(paragraph.itertext()).strip()
        if (len(chain) >= 3 and index > 0) or len(text) > 160:
            property_node(property_node(paragraph, "pPr"), "keepNext").set(w("val"), "0")


def compatible_sections(left, right):
    """仅同纸张、列宽、页边距及页眉页脚的节可以顺接"""
    names = (
        "pgSz",
        "pgMar",
        "cols",
        "docGrid",
        "textDirection",
        "vAlign",
        "headerReference",
        "footerReference",
        "titlePg",
        "footnotePr",
        "endnotePr",
    )
    return all(
        [etree.tostring(node) for node in left.findall(w(name))]
        == [etree.tostring(node) for node in right.findall(w(name))]
        for name in names
    )


def compact_flow(root, definitions):
    """自动压页后阶才放松通用分页规则，复杂定位和图像尺寸保持原样"""
    blocks = flow_blocks(root)
    if not blocks:
        return
    paragraphs = {node for block in blocks for node in block.iter(w("p"))}
    parents = set()
    for paragraph in paragraphs:
        props = property_node(paragraph, "pPr")
        if text_only(paragraph):
            property_node(props, "snapToGrid").set(w("val"), "0")
            if paragraph_flag(paragraph, definitions, "pageBreakBefore"):
                property_node(props, "pageBreakBefore").set(w("val"), "0")
            if paragraph_flag(paragraph, definitions, "keepLines"):
                property_node(props, "keepLines").set(w("val"), "0")
            parents.add(paragraph.getparent())
            for node in paragraph.findall(".//w:br[@w:type='page']", NS):
                node.attrib.pop(w("type"), None)
    for node in [node for block in blocks for node in block.iter(w("lastRenderedPageBreak"))]:
        node.getparent().remove(node)
    for parent in parents:
        chain = []
        for node in [*parent, None]:
            if (
                node is not None
                and node in paragraphs
                and text_only(node)
                and paragraph_flag(node, definitions, "keepNext")
            ):
                chain.append(node)
            else:
                release_chain(chain)
                chain = []
    for row in (node for block in blocks for node in block.iter(w("tr"))):
        if not text_only(row):
            continue
        props = row.find(w("trPr"))
        if props is not None:
            for height in list(props.findall(w("trHeight"))):
                props.remove(height)
            if props.find(w("cantSplit")) is not None:
                property_node(props, "cantSplit").set(w("val"), "0")
    sections = [node for block in blocks for node in block.iter(w("sectPr"))]
    for previous, current in zip(sections, sections[1:], strict=False):
        if compatible_sections(previous, current):
            property_node(current, "type").set(w("val"), "continuous")
