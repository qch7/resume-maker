"""为新增大栏目复制现有标题样式，并扩展普通经历条目的填写位置。"""

from copy import deepcopy
from io import BytesIO

from lxml import etree

from resume_maker.domain.templates import RepeatBinding, TextBinding
from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.template_entry_layout import (
    ParagraphStyles,
    apply_indent,
    common_indent,
)
from resume_maker.integrations.word.template_flow import flow_paragraph
from resume_maker.integrations.word.template_layout import child_in
from resume_maker.integrations.word.template_map import IMAGE_TAGS, TemplatePackage, paragraph_text
from resume_maker.integrations.word.template_supplement import remap_plan
from resume_maker.integrations.word.template_values import required_entry_fields, section_records

ENTRY_SLOT = "〔自动条目占位〕"


def section_headings(package, plan, document):
    """从标题映射和已确认的固定标题中寻找可复用的大栏目完整块。"""
    children = {section.title for section in document.sections if section.parent_id}
    regions = {region.section: region for region in plan.repeats}
    titles = set(regions) | {section.title for section in document.sections}
    fields = [field for field in plan.fields if field.target.startswith("section-title:")]
    bound = {field.node for field in fields}
    for identifier in plan.keep:
        node = package.node(identifier)
        literal = paragraph_text(node)
        title = literal.strip().rstrip("：:")
        if node.tag == w("p") and identifier not in bound and title in titles | {"项目经历"}:
            fields.append(
                TextBinding(node=identifier, quote=literal, target=f"section-title:{title}")
            )
    result = []
    for field in fields:
        title = field.target.partition(":")[2]
        if title in children or package.locations[field.node] != "word/document.xml":
            continue
        node = package.node(field.node)
        project = any(
            section.title == title and section.kind == "projects" for section in document.sections
        )
        region = regions.get(title) or (regions.get("projects") if project else None)
        if region is None:
            continue
        start = package.node(region.start)
        parent = next(
            (
                ancestor
                for ancestor in node.iterancestors()
                if ancestor.tag in {w("body"), w("tbl"), w("tc"), w("sdtContent")}
                and ancestor in start.iterancestors()
            ),
            None,
        )
        if parent is None:
            continue
        root = child_in(node, parent)
        descendants = package.descendants([root])
        if any(
            item.node in descendants and item.target.startswith("personal.") for item in plan.fields
        ):
            continue
        if set(plan.photos) & descendants or any(r.start in descendants for r in plan.repeats):
            continue
        if any(
            paragraph is not node and paragraph_text(paragraph).strip()
            for paragraph in root.iter(w("p"))
        ):
            continue
        result.append((root, field, parent))
    order = {node: index for index, node in enumerate(package.nodes.values())}
    return sorted(result, key=lambda item: order[item[0]])


def entry_donor(package, plan, target, region=None):
    """优先沿用同栏目同字段或正文的字体，缺少时借用其他普通经历的文字样式。"""
    regions = ([region] if region is not None else []) + [
        r for r in plan.repeats if r is not region
    ]
    for key in (target, "details", "description", "title"):
        for candidate in regions:
            for field in candidate.fields:
                if field.target == key:
                    return package.node(field.node)
    return None


def entry_paragraph(package, plan, target, styles, region=None):
    """以模板正文字体建立可换行的条目字段，标题加粗，正文不继承固定位置或分页。"""
    paragraph = flow_paragraph(ENTRY_SLOT, entry_donor(package, plan, target, region))
    properties = paragraph.find(w("pPr"))
    for tag in ("numPr", "pBdr", "shd"):
        node = properties.find(w(tag))
        if node is not None:
            properties.remove(node)
    geometry = region or next(
        (
            candidate
            for candidate in plan.repeats
            if any(field.target in {"details", "description"} for field in candidate.fields)
        ),
        plan.repeats[0] if plan.repeats else None,
    )
    indent = (
        common_indent(styles, package.nodes, geometry.fields)
        if geometry is not None
        else {w("left"): "0"}
    )
    styles.isolate_indent(paragraph, indent)
    apply_indent(paragraph, indent, unnumbered=True)
    if target == "title":
        run = paragraph.find(w("r"))
        style = run.find(w("rPr"))
        if style is None:
            style = etree.Element(w("rPr"))
            run.insert(0, style)
        bold = style.find(w("b"))
        if bold is None:
            bold = etree.SubElement(style, w("b"))
        bold.set(w("val"), "1")
        etree.SubElement(properties, w("keepNext"))
    return paragraph


def entry_blocks(parent, paragraphs):
    """普通容器使用段落，表格栏目使用跨满原列宽的一行，避免生成非法表格结构。"""
    if parent.tag != w("tbl"):
        return paragraphs
    row, cell = etree.Element(w("tr")), etree.Element(w("tc"))
    properties = etree.SubElement(cell, w("tcPr"))
    columns = len(parent.findall("w:tblGrid/w:gridCol", NS))
    if columns > 1:
        etree.SubElement(properties, w("gridSpan")).set(w("val"), str(columns))
    cell.extend(paragraphs)
    row.append(cell)
    return [row]


def cloned_heading(package, root, field, index):
    """复制标题的全部图形与样式，仅清理身份和分节标记，返回克隆后的标题文字节点。"""
    clone = deepcopy(root)
    pairs = dict(zip(root.iter(), clone.iter(), strict=True))
    title = pairs[package.node(field.node)]
    for node in list(clone.iter()):
        for attribute in list(node.attrib):
            if etree.QName(attribute).localname in {"paraId", "textId", "anchorId", "editId"}:
                del node.attrib[attribute]
        if node.tag in {w("bookmarkStart"), w("bookmarkEnd"), w("sectPr")}:
            node.getparent().remove(node)
        elif etree.QName(node).localname == "shape" and node.get("id"):
            node.set("id", f"{node.get('id')}-resume-section-{index}")
    return clone, title


def supplement_sections(package, plan, document, projects):
    """在本次输出副本补齐大栏目及普通条目字段，原文件和用户保存的映射始终不变。"""
    records = {
        section.title: section_records(document, section.title, projects)
        for section in document.sections
    }
    requirements = []
    additions = []
    for section in document.sections:
        if not records.get(section.title):
            continue
        regions = [
            region
            for region in plan.repeats
            if region.section == section.title
            or (section.kind == "projects" and region.section == "projects")
        ]
        required = required_entry_fields(records[section.title], project=section.kind == "projects")
        if section.kind == "projects":
            required = [key for key in required if key == "custom_fields"]
        if not regions and section.kind != "projects" and not section.parent_id and required:
            additions.append((section, required))
        for region in regions:
            if section.kind == "projects" and any(
                field.target == "details" for field in region.fields
            ):
                continue
            missing = [
                key for key in required if key not in {field.target for field in region.fields}
            ]
            if missing:
                requirements.append((plan.repeats.index(region), section.title, missing))
    if not requirements and not additions:
        return package, plan, []
    if not package.review(plan)["ready"]:
        return package, plan, []
    buffer = BytesIO()
    package.write(buffer)
    working = TemplatePackage(buffer)
    styles = ParagraphStyles(working)
    previous = dict(working.nodes)
    extensions, sections, notices = [], [], []
    for index, title, missing in requirements:
        region = plan.repeats[index]
        sample = working.region(region.sample_start, region.sample_end)
        parent = sample[0].getparent()
        metadata = [key for key in missing if key in {"title", "subtitle", "period"}]
        trailing = [key for key in missing if key not in metadata]
        fields = []
        before, after = [], []
        for targets, blocks in ((metadata, before), (trailing, after)):
            paragraphs = [entry_paragraph(working, plan, key, styles, region) for key in targets]
            fields.extend(zip(paragraphs, targets, strict=True))
            blocks.extend(entry_blocks(parent, paragraphs) if paragraphs else [])
        # 已有标题时，补充信息和时间放在标题之后；只有正文样本时才在正文前补标题信息。
        title_nodes = [
            child_in(working.node(field.node), parent)
            for field in region.fields
            if field.target == "title"
        ]
        position = (
            max(parent.index(node) for node in title_nodes) + 1
            if title_nodes
            else parent.index(sample[0])
        )
        for block in before:
            parent.insert(position, block)
            position += 1
        position = max(parent.index(node) for node in [*sample, *before]) + 1
        for block in after:
            parent.insert(position, block)
            position += 1
        extended = sorted([*before, *sample, *after], key=parent.index)
        first, last = extended[0], extended[-1]
        extensions.append((index, first, last, fields))
        notices.append(f"已沿用原文字样式补充“{title}”的条目字段。")
    headings = section_headings(working, plan, document)
    for index, (section, targets) in enumerate(additions):
        if not headings:
            continue
        root, title_field, parent = headings[0]
        heading, title_node = cloned_heading(working, root, title_field, index)
        # 插在已知栏目尾部、固定结尾之前，随后交由统一栏目编排按当前顺序放置。
        anchors = [item[0] for item in headings if item[2] is parent]
        anchors.extend(
            child_in(working.node(region.end), parent)
            for region in plan.repeats
            if parent in working.node(region.end).iterancestors()
        )
        anchors.extend(item[0][-1] for item in sections if item[0][-1].getparent() is parent)
        anchors.extend(last for _, _, last, _ in extensions if last.getparent() is parent)
        position = max(parent.index(node) for node in anchors) + 1
        paragraphs = [entry_paragraph(working, plan, target, styles) for target in targets]
        blocks = entry_blocks(parent, paragraphs)
        for offset, block in enumerate([heading, *blocks]):
            parent.insert(position + offset, block)
        sections.append(
            (
                blocks,
                title_node,
                title_field,
                section.title,
                list(zip(paragraphs, targets, strict=True)),
                heading,
            )
        )
        notices.append(
            f"已沿用“{title_field.target.partition(':')[2]}”的大标题样式新增“{section.title}”。"
        )
    if not extensions and not sections:
        return package, plan, []
    working.reindex()
    updated = remap_plan(plan, previous, working)
    for index, first, last, fields in extensions:
        region = updated.repeats[index]
        if region.start == region.sample_start:
            region.start = working.ids[first]
        if region.end == region.sample_end:
            region.end = working.ids[last]
        region.sample_start, region.sample_end = working.ids[first], working.ids[last]
        region.fields.extend(
            TextBinding(node=working.ids[node], quote=ENTRY_SLOT, target=target)
            for node, target in fields
        )
    for blocks, title_node, title_field, title, fields, heading in sections:
        updated.fields.append(
            title_field.model_copy(
                update={"node": working.ids[title_node], "target": f"section-title:{title}"}
            )
        )
        updated.repeats.append(
            RepeatBinding(
                section=title,
                start=working.ids[blocks[0]],
                end=working.ids[blocks[-1]],
                sample_start=working.ids[blocks[0]],
                sample_end=working.ids[blocks[-1]],
                fields=[
                    TextBinding(node=working.ids[node], quote=ENTRY_SLOT, target=target)
                    for node, target in fields
                ],
            )
        )
        updated.keep.extend(working.ids[node] for node in heading.iter() if node.tag in IMAGE_TAGS)
    if not working.review(updated)["ready"]:
        return package, plan, []
    working.notices = [*package.notices, *notices]
    return working, updated, notices
