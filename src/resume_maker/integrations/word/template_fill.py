"""按已核对映射填充陌生模板，复制原样式并按实际记录增减重复区。"""

import base64
import posixpath
from copy import deepcopy
from pathlib import Path

from lxml import etree

from resume_maker.core.errors import Problem
from resume_maker.domain.resume import ResumeDocument
from resume_maker.domain.templates import TemplatePlan, TextBinding
from resume_maker.integrations.word.full_resume import displayed_entries, visible_custom_fields
from resume_maker.integrations.word.ooxml import w
from resume_maker.integrations.word.template_flow import (
    effective_section,
    flow_record,
    requires_flow,
)
from resume_maker.integrations.word.template_map import (
    IMAGE_TAGS,
    NS,
    TemplatePackage,
    image_container,
    paragraph_text,
    paragraph_texts,
    quote_range,
    relationship_part,
    relationship_target,
)

CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"


def custom_text(fields) -> str:
    """按用户顺序输出可见自定义信息，不输出空名称或空值。"""
    return "\n".join(f"{field.label}：{field.value}" for field in visible_custom_fields(fields))


def section_records(document: ResumeDocument, title: str, projects: list[dict]) -> list[dict]:
    """按栏目名称取可见记录，项目区始终使用用户选定的固定经历版本。"""
    candidates = [
        section
        for section in document.sections
        if section.title == title or (title == "projects" and section.kind == "projects")
    ]
    if len(candidates) > 1:
        raise Problem(f"存在重名栏目“{title}”，请先为栏目设置独立名称。")
    if not candidates:
        return []
    section = candidates[0]
    parent = next((s for s in document.sections if s.id == section.parent_id), None)
    if not section.visible or (parent is not None and not parent.visible):
        return []
    if section.kind == "projects":
        records = []
        for project in projects:
            value = project["content"]
            points = {point["id"]: point for point in value["highlights"]}
            highlights = "\n".join(
                f"{points[identifier]['title']}：{points[identifier]['text']}"
                for identifier in project["highlight_ids"]
            )
            stack = "、".join(value["stack"])
            details = "\n".join(
                filter(
                    None,
                    [
                        f"技术栈：{stack}" if stack else "",
                        f"担任角色：{value['role']}" if value["role"] else "",
                        value["description"],
                        highlights,
                    ],
                )
            )
            records.append(
                {
                    **value,
                    "stack": stack,
                    "highlights": highlights,
                    "details": details,
                    "subtitle": value["role"],
                    "custom_fields": "",
                }
            )
        return records
    return [
        {**entry.model_dump(), "custom_fields": custom_text(entry.custom_fields)}
        for entry in displayed_entries(section)
    ]


def personal_values(document: ResumeDocument) -> dict[str, str]:
    """将资料字段转为替换值；隐藏字段清空，照片由独立图片映射处理。"""
    personal = document.personal
    values = {
        f"personal.{key}": "" if key in personal.hidden_fields else value
        for key, value in personal.model_dump().items()
        if isinstance(value, str)
    }
    values["personal.custom_fields"] = custom_text(personal.custom_fields)
    values.update(
        {
            f"personal.custom:{field.label}": field.value
            for field in visible_custom_fields(personal.custom_fields)
        }
    )
    values.update(
        {
            f"section-title:{section.title}": section.title
            if section.visible
            and not any(
                parent.id == section.parent_id and not parent.visible
                for parent in document.sections
            )
            else ""
            for section in document.sections
        }
    )
    return values


def missing_targets(
    document: ResumeDocument, plan: TemplatePlan, projects: list[dict]
) -> list[str]:
    """列出当前非空资料缺少的位置，防止导出时静默丢失姓名、栏目或照片。"""
    targets = {field.target for field in plan.fields}
    values = personal_values(document)
    missing = []
    labels = [field.label for field in visible_custom_fields(document.personal.custom_fields)]
    if len(labels) != len(set(labels)) and "personal.custom_fields" not in targets:
        missing.append("重名自定义信息请使用“全部自定义信息”映射或修改名称")
    for target, value in values.items():
        if not value or not target.startswith("personal."):
            continue
        if target == "personal.photo":
            if not plan.photos:
                missing.append("照片")
        elif target == "personal.custom_fields":
            continue
        elif target.startswith("personal.custom:") and "personal.custom_fields" in targets:
            continue
        elif target not in targets:
            missing.append(target)
    for section in document.sections:
        records = section_records(document, section.title, projects)
        if not records:
            continue
        regions = [
            region
            for region in plan.repeats
            if region.section == section.title
            or (region.section == "projects" and section.kind == "projects")
        ]
        if not regions:
            missing.append(f"栏目：{section.title}")
            continue
        for region in regions:
            bound = {field.target for field in region.fields}
            required = (
                {"title", "period", "role", "stack", "description", "highlights"}
                if section.kind == "projects"
                else {"title", "subtitle", "period", "details", "custom_fields"}
            )
            if section.kind == "projects" and "details" in bound:
                required -= {"role", "stack", "description", "highlights"}
            for field in required - bound:
                if any(record.get(field) for record in records):
                    missing.append(f"{section.title} · {field}")
    return list(dict.fromkeys(missing))


def set_text(node, value: str):
    """保留原文本片段样式，把用户换行转换为 Word 换行节点。"""
    parent, index = node.getparent(), node.getparent().index(node)
    parent.remove(node)
    for offset, line in enumerate(value.split("\n")):
        if offset:
            parent.insert(index, etree.Element(w("br")))
            index += 1
        text = etree.Element(w("t"))
        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text.text = line
        parent.insert(index, text)
        index += 1


def fill_fields(nodes: dict, fields: list[TextBinding], values: dict):
    """从段落末尾向前替换引文，保留相邻文字和样式，移除旧超链接行为。"""
    grouped = {}
    for binding in fields:
        node = nodes[binding.node]
        start, end = quote_range(paragraph_text(node), binding)
        value = str(values.get(binding.target, ""))
        if value and not binding.quote and binding.target.startswith("personal.custom:"):
            value = binding.target.partition(":")[2] + "：" + value
        grouped.setdefault(binding.node, []).append((start, end, value))
    for identifier, replacements in grouped.items():
        paragraph = nodes[identifier]
        modified_links = set()
        for start, end, value in sorted(replacements, reverse=True):
            if start == end == 0:
                run = next(iter(paragraph.findall(w("r"))), None)
                if run is None:
                    run = etree.SubElement(paragraph, w("r"))
                set_text(etree.SubElement(run, w("t")), value)
                continue
            # 清除被整段引文覆盖的旧换行和制表符，避免旧样本空行留在新正文中。
            position = 0
            for child in list(paragraph.iter()):
                if next(child.iterancestors(w("p")), None) is not paragraph:
                    continue
                if child.tag == w("t"):
                    position += len(child.text or "")
                elif child.tag in {w("br"), w("cr"), w("tab")} and start < position < end:
                    child.getparent().remove(child)
            position, inserted = 0, False
            for text in paragraph_texts(paragraph):
                original = text.text or ""
                limit = position + len(original)
                if position < end and start < limit:
                    link = next(text.iterancestors(w("hyperlink")), None)
                    if link is not None:
                        modified_links.add(link)
                    prefix = original[: max(0, start - position)]
                    suffix = original[max(0, end - position) :]
                    set_text(text, prefix + (value if not inserted else "") + suffix)
                    inserted = True
                position = limit
        for link in modified_links:
            if next(link.iterancestors(w("p")), None) is not paragraph:
                continue
            parent = link.getparent()
            for child in list(link):
                parent.insert(parent.index(link), child)
            parent.remove(link)


def remove_node(node):
    """删除文字区域或图片容器，保留相邻段落与表格结构。"""
    if node.tag in IMAGE_TAGS:
        node = image_container(node)
    node.getparent().remove(node)


def fill_photo(package: TemplatePackage, identifier: str, photo: str):
    """更换选定图片关系并沿用照片框尺寸，隐藏照片时仅移除该图片。"""
    node = package.node(identifier)
    if not photo:
        remove_node(node)
        return
    part = package.locations[identifier]
    rel_path = relationship_part(part)
    root = etree.fromstring(
        package.files[rel_path], etree.XMLParser(resolve_entities=False, no_network=True)
    )
    attribute = f"{{{NS['r']}}}{'embed' if node.tag.endswith('blip') else 'id'}"
    old_id = node.get(attribute)
    old = next((item for item in root if item.get("Id") == old_id), None)
    if old is None or old.get("TargetMode") == "External":
        raise Problem("照片引用无效，请使用内嵌图片模板。")
    extension = "png" if photo.startswith("data:image/png;") else "jpg"
    media = f"word/media/resume-maker-{identifier}.{extension}"
    package.files[media] = base64.b64decode(photo.partition(",")[2], validate=True)
    rel_id = f"resumeMaker{identifier}"
    if any(item.get("Id") == rel_id for item in root):
        raise Problem("模板含重复的照片映射标识，请重新导入原文档。")
    relationship = deepcopy(old)
    relationship.set("Id", rel_id)
    relationship.set("Target", posixpath.relpath(media, posixpath.dirname(part)))
    root.append(relationship)
    node.set(attribute, rel_id)
    node.attrib.pop(f"{{{NS['r']}}}link", None)
    picture = next((p for p in node.iterancestors() if p.tag in {w("drawing"), w("pict")}), None)
    if picture is not None:
        for metadata in picture.xpath(".//*[local-name()='docPr' or local-name()='cNvPr']"):
            metadata.attrib.pop("descr", None)
            metadata.attrib.pop("title", None)
            metadata.set("name", "Photo")
        for crop in picture.xpath(".//a:srcRect", namespaces=NS):
            crop.getparent().remove(crop)
    package.files[rel_path] = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
    types = etree.fromstring(
        package.files["[Content_Types].xml"],
        etree.XMLParser(resolve_entities=False, no_network=True),
    )
    if not any(item.get("Extension") == extension for item in types):
        etree.SubElement(
            types,
            f"{{{CONTENT_TYPES}}}Default",
            Extension=extension,
            ContentType="image/png" if extension == "png" else "image/jpeg",
        )
    package.files["[Content_Types].xml"] = etree.tostring(
        types, xml_declaration=True, encoding="UTF-8"
    )


def clean_resources(package: TemplatePackage):
    """移除已不再使用的旧照片和链接资源，保留其他部件仍在引用的装饰图片。"""
    referenced = set()
    for name, data in list(package.files.items()):
        if not name.endswith(".rels"):
            continue
        root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
        folder, filename = posixpath.split(name)
        parent = posixpath.dirname(folder)
        part = posixpath.join(parent, filename[:-5])
        used = None
        if part in package.parts:
            used = {
                value
                for node in package.parts[part].iter()
                for key, value in node.attrib.items()
                if key.startswith(f"{{{NS['r']}}}")
            }
        for rel in list(root):
            if (
                used is not None
                and rel.get("Id") not in used
                and rel.get("Type", "").endswith(("/image", "/hyperlink"))
            ):
                root.remove(rel)
            elif rel.get("TargetMode") != "External":
                referenced.add(relationship_target(part, rel.get("Target", "")))
        package.files[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
    removed = {
        name for name in package.files if name.startswith("word/media/") and name not in referenced
    }
    for name in removed:
        del package.files[name]
    types = etree.fromstring(
        package.files["[Content_Types].xml"],
        etree.XMLParser(resolve_entities=False, no_network=True),
    )
    for item in list(types):
        if item.get("PartName", "").lstrip("/") in removed:
            types.remove(item)
    package.files["[Content_Types].xml"] = etree.tostring(
        types, xml_declaration=True, encoding="UTF-8"
    )


def section_marker(properties):
    """用空段落保存一次分节设置，使删去的内容不改变相邻区域的页面排版。"""
    paragraph = etree.Element(w("p"))
    etree.SubElement(paragraph, w("pPr")).append(deepcopy(properties))
    return paragraph


def remove_preserving_sections(node):
    """删除旧示例时保留其分节边界，避免相邻正文继承错误的分栏或页边距。"""
    parent = node.getparent()
    if parent is not None:
        position = parent.index(node)
        for properties in node.iter(w("sectPr")):
            parent.insert(position, section_marker(properties))
            position += 1
    remove_node(node)


def fill_template(
    source: Path, output: Path, plan: TemplatePlan, content: dict, projects: list[dict]
):
    """仅执行通过结构与资料覆盖校验的映射，每次导出都从原模板重新生成。"""
    package = TemplatePackage(source)
    review = package.review(plan)
    if not review["ready"]:
        raise Problem(
            "模板映射尚未完成：" + "；".join(review["errors"] or ["还有未处理的原文或图片"])
        )
    document = ResumeDocument.model_validate(content)
    missing = missing_targets(document, plan, projects)
    if missing:
        raise Problem("模板未覆盖这些已填写资料，请补充映射或在资料中隐藏：" + "、".join(missing))
    fill_fields(package.nodes, plan.fields, personal_values(document))
    for region in plan.repeats:
        original = package.region(region.start, region.end)
        sample = package.region(region.sample_start, region.sample_end)
        parent, position = original[0].getparent(), original[0].getparent().index(original[0])
        records = section_records(document, region.section, projects)
        if records and requires_flow(sample):
            leading = effective_section(original[0])
            if leading is not None:
                parent.insert(position, section_marker(leading))
                position += 1
            for record in records:
                for node in flow_record(package, region, record, plan.keep):
                    parent.insert(position, node)
                    position += 1
            if leading is not None:
                closing = deepcopy(leading)
                columns = closing.find(w("cols"))
                if columns is not None:
                    closing.remove(columns)
                etree.SubElement(closing, w("cols")).set(w("num"), "1")
                kind = closing.find(w("type"))
                if kind is None:
                    kind = etree.SubElement(closing, w("type"))
                kind.set(w("val"), "continuous")
                parent.insert(position, section_marker(closing))
            for node in original:
                parent.remove(node)
            continue
        has_sections = any(list(node.iter(w("sectPr"))) for node in sample)
        # 多栏标题和单栏正文同属一条经历；每条复制结束时闭合原有连续分节。
        trailing = (
            next(iter(sample[-1].xpath("following::w:sectPr[1]", namespaces=NS)), None)
            if has_sections
            else None
        )
        if list(sample[-1].iter(w("sectPr"))):
            trailing = None
        for record in records:
            clones = [deepcopy(node) for node in sample]
            nodes = {
                package.ids[old]: new
                for old_root, new_root in zip(sample, clones, strict=True)
                for old, new in zip(old_root.iter(), new_root.iter(), strict=True)
            }
            fill_fields(nodes, region.fields, record)
            for clone in clones:
                # 复制样本时不复制书签身份，避免不同记录共享同一个 Word 锚点。
                for bookmark in list(clone.iter(w("bookmarkStart"), w("bookmarkEnd"))):
                    bookmark.getparent().remove(bookmark)
                parent.insert(position, clone)
                position += 1
            if trailing is not None:
                marker = section_marker(trailing)
                section_type = marker.find(".//w:sectPr/w:type", NS)
                if section_type is None:
                    section_type = etree.SubElement(marker.find(".//w:sectPr", NS), w("type"))
                section_type.set(w("val"), "continuous")
                parent.insert(position, marker)
                position += 1
        if not records:
            for node in original:
                for properties in node.iter(w("sectPr")):
                    parent.insert(position, section_marker(properties))
                    position += 1
        for node in original:
            parent.remove(node)
    values = personal_values(document)
    for identifier in plan.photos:
        fill_photo(package, identifier, values["personal.photo"])
    for identifier in plan.remove:
        remove_preserving_sections(package.node(identifier))
    drawing_id = 0
    control_id = 0
    for root in package.parts.values():
        for table in list(root.iter(w("tbl"))):
            if not any(
                next(row.iterancestors(w("tbl")), None) is table for row in table.iter(w("tr"))
            ):
                remove_node(table)
        for cell in root.iter(w("tc")):
            if not len(cell) or cell[-1].tag != w("p"):
                etree.SubElement(cell, w("p"))
        for drawing in root.xpath(".//*[local-name()='docPr']"):
            drawing_id += 1
            drawing.set("id", str(drawing_id))
        for control in root.xpath(".//w:sdtPr/w:id", namespaces=NS):
            control_id += 1
            control.set(w("val"), str(control_id))
    clean_resources(package)
    package.write(output)
