"""把模板中已识别的栏目作为整体编排；标题、样式与记录始终一起移动"""

from collections import defaultdict
from copy import deepcopy

from lxml import etree

from resume_maker.core.errors import Problem
from resume_maker.domain.templates import TextBinding
from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.templates.anchors import page_positioned
from resume_maker.integrations.word.templates.flow import (
    continuous_block,
    continuous_section,
    effective_section,
    flow_paragraph,
)
from resume_maker.integrations.word.templates.mapping import paragraph_text, paragraph_texts

WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
CONTAINERS = {w(tag) for tag in ("body", "tbl", "tc", "sdtContent", "txbxContent")}


def independent_containers(anchors):
    """仅将完整落在互不包含的单元格或文本框内的栏目分组；保留模板原有二维布局"""
    groups = defaultdict(list)
    for title, nodes in anchors.items():
        parent = next(
            (
                parent
                for parent in nodes[0].iterancestors()
                if parent.tag in {w("tc"), w("txbxContent")}
                and all(parent in node.iterancestors() for node in nodes)
            ),
            None,
        )
        if parent is None:
            return {}
        groups[parent].append(title)
    if len(groups) < 2 or any(
        parent in other.iterancestors()
        for parent in groups
        for other in groups
        if parent is not other
    ):
        return {}
    return groups


def child_in(node, parent):
    """取得节点在指定容器中的直接子块以免把表格行和段落混为同级"""
    while node.getparent() is not parent:
        node = node.getparent()
        if node is None:
            raise Problem("栏目不在同一排版容器中，请调整模板的栏目边界。")
    return node


def inline_drawing(block, following=None):
    """栏目标题改为嵌入式时保留水平位置；抵扣原来用于给悬浮标题让位的段前空白"""
    anchors = block.findall(f".//{{{WP}}}anchor")
    converted = False
    for anchor in anchors:
        horizontal = anchor.find(f"{{{WP}}}positionH")
        offset = horizontal.find(f"{{{WP}}}posOffset") if horizontal is not None else None
        if (
            block.tag != w("p")
            or block.getparent() is None
            or block.getparent().tag != w("body")
            or horizontal is None
            or offset is None
            or horizontal.get("relativeFrom") not in {"page", "margin"}
        ):
            # 字符、分栏、单元格或对齐式定位不能用页面左边距换算；保留原生锚点
            continue
        if block.tag == w("p"):
            properties = block.find(w("pPr"))
            if properties is None:
                properties = etree.Element(w("pPr"))
                block.insert(0, properties)
            section = effective_section(block)
            margins = section.find(w("pgMar")) if section is not None else None
            if horizontal is not None and offset is not None and margins is not None:
                if horizontal.get("relativeFrom") in {"page", "margin"}:
                    left = round(int(offset.text or "0") / 635)
                    if horizontal.get("relativeFrom") == "page":
                        left -= int(margins.get(w("left"), "0"))
                    indent = properties.find(w("ind"))
                    if indent is None:
                        indent = etree.SubElement(properties, w("ind"))
                    indent.set(w("left"), str(left))
            extent = anchor.find(f"{{{WP}}}extent")
            following = following if following is not None else block.getnext()
            while following is not None and not isinstance(following.tag, str):
                following = following.getnext()
            spacing = following.find("w:pPr/w:spacing", NS) if following is not None else None
            own_spacing = properties.find(w("spacing"))
            if (
                anchor.find(f"{{{WP}}}wrapNone") is not None
                and extent is not None
                and spacing is not None
                and own_spacing is not None
                and own_spacing.get(w("lineRule")) == "exact"
                and own_spacing.get(w("line")) == "1"
            ):
                before = int(spacing.get(w("before"), "0"))
                spacing.set(
                    w("before"), str(max(0, before - round(int(extent.get("cy", "0")) / 635)))
                )
        anchor.tag = f"{{{WP}}}inline"
        converted = True
        anchor.attrib.clear()
        for child in list(anchor):
            if etree.QName(child).localname not in {
                "extent",
                "effectExtent",
                "docPr",
                "cNvGraphicFramePr",
                "graphic",
            }:
                anchor.remove(child)
    if converted and block.tag == w("p"):
        properties = block.find(w("pPr"))
        spacing = properties.find(w("spacing")) if properties is not None else None
        if spacing is not None:
            spacing.attrib.pop(w("line"), None)
            spacing.attrib.pop(w("lineRule"), None)


def inline_heading(block, following=None):
    """标题图形保留原字体与装饰并与第一段正文保持同页"""
    inline_drawing(block, following)
    if block.tag == w("p"):
        properties = block.find(w("pPr"))
        if properties is None:
            properties = etree.Element(w("pPr"))
            block.insert(0, properties)
        if properties.find(w("keepNext")) is None:
            etree.SubElement(properties, w("keepNext"))


class TemplateLayout:
    """在填充前标记栏目区段；填充后按当前层级重排；不改变源模板或正式资料"""

    def __init__(self, package, plan, document, records, values):
        """由标题和完整重复范围确定栏目归属；兼容正文段落及表格行"""
        self.parent = None
        self.children = []
        self.notices = []
        self.segments = []
        self.fields = list(plan.fields)
        self.values = {}
        self.visible = set()
        self.order = []
        self.headings = []
        self.shared_headings = []
        self.empty_labels = []
        self.fixed = []
        sections = {section.title: section for section in document.sections}
        project_title = next(s.title for s in document.sections if s.kind == "projects")
        aliases = {"projects": project_title}
        anchors = defaultdict(list)
        title_fields = []
        for field in plan.fields:
            if field.target.startswith("section-title:"):
                title = field.target.partition(":")[2]
                node = package.node(field.node)
                if package.locations[field.node] == "word/document.xml":
                    anchors[title].append(node)
                    title_fields.append((title, field))
        for region in plan.repeats:
            title = aliases.get(region.section, region.section)
            if package.locations[region.start] == "word/document.xml":
                anchors[title].extend(package.region(region.start, region.end))
        # 旧映射把固定栏目标题放在 keep 中时且仅识别与已知栏目完全相同的文字
        bound = {field.node for field in plan.fields}
        for identifier in plan.keep:
            node = package.node(identifier)
            if node.tag != w("p") or identifier in bound:
                continue
            literal = paragraph_text(node)
            title = literal.strip().rstrip("：:")
            if title == "项目经历":
                title = project_title
            if title in anchors and package.locations[identifier] == "word/document.xml":
                binding = TextBinding(
                    node=identifier, quote=literal, target=f"section-title:{title}"
                )
                anchors[title].append(node)
                title_fields.append((title, binding))
                self.fields.append(binding)
        nodes = [node for group in anchors.values() for node in group]
        if not nodes or (len(anchors) == 1 and not title_fields):
            return
        for container, titles in independent_containers(anchors).items():
            identifiers = package.descendants([container])
            subset = plan.model_copy(
                update={
                    "fields": [field for field in plan.fields if field.node in identifiers],
                    "repeats": [
                        region
                        for region in plan.repeats
                        if aliases.get(region.section, region.section) in titles
                    ],
                    "keep": [identifier for identifier in plan.keep if identifier in identifiers],
                    "photos": [
                        identifier for identifier in plan.photos if identifier in identifiers
                    ],
                }
            )
            child = TemplateLayout(package, subset, document, records, values)
            self.children.append(child)
            self.fields = [
                field for field in self.fields if field.node not in identifiers
            ] + child.fields
            self.values.update(child.values)
        if self.children:
            self.notices.append(
                "栏目位于独立的单元格或文本框中，已保留原有位置，排序只在各容器内部生效。"
            )
            return
        self.parent = next(
            (
                parent
                for parent in nodes[0].iterancestors()
                if parent.tag in CONTAINERS
                and all(parent in node.iterancestors() for node in nodes)
            ),
            None,
        )
        if self.parent is None:
            raise Problem("模板栏目分布在不能独立移动的容器中，请调整模板栏目边界。")
        blocks = list(self.parent)
        spans = {}
        for title, group in anchors.items():
            positions = [blocks.index(child_in(node, self.parent)) for node in group]
            spans[title] = min(positions), max(positions)
        for title, (start, end) in spans.items():
            for other, (left, right) in spans.items():
                if other == title:
                    continue
                if (start, end) == (left, right) or start < left <= end < right:
                    raise Problem(f"模板的“{title}”与“{other}”共用或交叉排版区域，请调整栏目边界。")
        first = min(start for start, _ in spans.values())
        last = max(end for _, end in spans.values())
        personal = defaultdict(list)
        for field in plan.fields:
            if field.target.startswith("personal.") and values.get(field.target):
                node = package.node(field.node)
                if self.parent in node.iterancestors():
                    personal[child_in(node, self.parent)].append(field.target)
        if values.get("personal.photo"):
            for identifier in plan.photos:
                node = package.node(identifier)
                if self.parent in node.iterancestors():
                    personal[child_in(node, self.parent)].append("personal.photo")
        owners = {}
        for position in range(first, last + 1):
            block = blocks[position]
            if block in personal and page_positioned(block):
                self.fixed.append(block)
            containing = [
                title for title, (start, end) in spans.items() if start <= position <= end
            ]
            if containing:
                # 一个子栏目与 GPA 等个人字段共用块时；保留在外层栏目且不能随空子栏目删除
                choose = max if block in personal else min
                owner = choose(containing, key=lambda title: spans[title][1] - spans[title][0])
            else:
                owner = max(
                    (title for title, (_, end) in spans.items() if end < position),
                    key=lambda title: spans[title][1],
                )
            owners[block] = owner
        for title in anchors:
            section = sections.get(title)
            if section is None or not section.visible:
                continue
            parent = next((s for s in document.sections if s.id == section.parent_id), None)
            if parent is not None and not parent.visible:
                continue
            if records.get(title) or any(owners.get(block) == title for block in personal):
                self.visible.add(title)
        # 父栏目没有直接资料但有可见子栏目时仍保留父标题；顺序与栏目编排界面一致
        for section in document.sections:
            if section.parent_id or not section.visible:
                continue
            children = [s for s in document.sections if s.parent_id == section.id]
            if any(child.title in self.visible for child in children):
                self.visible.add(section.title)
            self.order.extend([section.title, *[child.title for child in children]])
        for title, binding in title_fields:
            self.values[binding.target] = title if title in self.visible else ""
            if title not in self.visible and sum(f.node == binding.node for f in self.fields) == 1:
                self.fields[self.fields.index(binding)] = binding.model_copy(
                    update={"quote": paragraph_text(package.node(binding.node)), "occurrence": 1}
                )
            block = child_in(package.node(binding.node), self.parent)
            if title in self.visible and owners.get(block) == title:
                self.headings.append(block)
            elif title in self.visible:
                # 例如“主修课程”与 GPA 共用一个锚定段落；标题随子栏目移动；GPA 留在教育区
                if any(
                    f.node == binding.node and f.target.startswith("personal.") for f in plan.fields
                ):
                    raise Problem(
                        f"“{title}”标题与个人资料共用同一段文字，请拆分模板中的标题段落。"
                    )
                self.shared_headings.append((title, package.node(binding.node)))
        for identifier in plan.keep:
            node = package.node(identifier)
            if self.parent not in node.iterancestors() or node.tag != w("p"):
                continue
            block = child_in(node, self.parent)
            owner = owners.get(block)
            if (
                owner is not None
                and not records.get(owner)
                and block not in personal
                and paragraph_text(node).strip().endswith((":", "："))
            ):
                self.empty_labels.append(node)
        # 标记连续区段而不是缓存旧子节点；填充器创建的记录也会留在对应标题下
        for position in range(first, last + 1):
            block = blocks[position]
            title = owners[block]
            if position == first or owners[blocks[position - 1]] != title:
                begin = etree.Comment("resume-section-start")
                block.addprevious(begin)
            if position == last or owners[blocks[position + 1]] != title:
                finish = etree.Comment("resume-section-end")
                block.addnext(finish)
                self.segments.append((title, begin, finish))
        # 最后一个栏目可能借用文档末尾的节属性；移动到中间时闭合其原有页面设置
        self.trailing = None
        if any(node.tag == w("sectPr") for block in owners for node in block.iter()):
            properties = effective_section(blocks[last])
            if properties is not None and not list(blocks[last].iter(w("sectPr"))):
                self.trailing = (owners[blocks[last]], deepcopy(properties))
        # 标题仍在原树中时计算横坐标和让位间距；重复样本会继承修正后的段前距离
        for block in self.headings:
            following = next(
                (
                    candidate
                    for candidate in blocks[blocks.index(block) + 1 :]
                    if owners.get(candidate) == owners.get(block)
                    and candidate.xpath(".//w:t[normalize-space()]", namespaces=NS)
                ),
                None,
            )
            inline_heading(block, following)

    def apply(self):
        """将填好的完整栏目按当前大栏目及子栏目顺序放回；空栏目连同旧标签一起省略"""
        for child in self.children:
            child.apply()
        if self.parent is None:
            return
        for block in self.fixed:
            # 组合页首即使借用教育或课程段落锚定；也不随栏目隐藏或移动到下一页
            self.parent.insert(self.parent.index(self.segments[0][1]), block)
        for node in self.empty_labels:
            if node.getparent() is not None:
                node.getparent().remove(node)
        groups = defaultdict(list)
        position = self.parent.index(self.segments[0][1])
        for title, begin, finish in self.segments:
            node = begin.getnext()
            while node is not finish:
                following = node.getnext()
                groups[title].append(node)
                self.parent.remove(node)
                node = following
            self.parent.remove(begin)
            self.parent.remove(finish)
        if self.trailing is not None:
            title, properties = self.trailing
            continuous_section(properties)
            marker = etree.Element(w("p"))
            etree.SubElement(marker, w("pPr")).append(properties)
            groups[title].append(marker)
        for title, node in self.shared_headings:
            heading = flow_paragraph(paragraph_text(node), node)
            inline_heading(heading)
            groups[title].insert(0, heading)
            for text in paragraph_texts(node):
                text.text = ""
        placed = []
        for title in self.order:
            if title not in self.visible:
                continue
            for node in groups[title]:
                self.parent.insert(position, node)
                position += 1
                placed.append(node)
        # 先放完再查有效节属性以免栏目重排时误用原位置后面的分节设置
        for block in placed:
            continuous_block(block)
