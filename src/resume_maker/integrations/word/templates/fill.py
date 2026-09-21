"""按已核对映射填充陌生模板；复制原样式并按实际记录增减重复区"""

import base64
import posixpath
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path

from lxml import etree

from resume_maker.core.errors import Problem
from resume_maker.domain.resume import ResumeDocument
from resume_maker.domain.templates import TemplatePlan, TextBinding
from resume_maker.integrations.word.ooxml import w
from resume_maker.integrations.word.pdf.geometry import clear_pdf_metadata
from resume_maker.integrations.word.pdf.header_layout import PDFHeaderLayout
from resume_maker.integrations.word.pdf.titles import fit_pdf_titles
from resume_maker.integrations.word.templates.completion import complete_template
from resume_maker.integrations.word.templates.entry_layout import ParagraphStyles, align_record
from resume_maker.integrations.word.templates.flow import effective_section
from resume_maker.integrations.word.templates.layout import TemplateLayout
from resume_maker.integrations.word.templates.mapping import (
    ENTRY_TARGETS,
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
from resume_maker.integrations.word.templates.personal import PersonalLayout, hidden_personal_range
from resume_maker.integrations.word.templates.project_order import (
    arrange_project_body,
    empty_project_range,
)
from resume_maker.integrations.word.templates.project_slots import prepare_project_slots
from resume_maker.integrations.word.templates.record_columns import (
    metadata_separator,
    prepare_record_columns,
)
from resume_maker.integrations.word.templates.values import (
    missing_targets,
    personal_values,
    section_records,
)

CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"


def set_text(node, value: str):
    """保留原文本片段样式；把用户换行转换为 Word 换行节点"""
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


def empty_entry_range(text, start, end):
    """字段独占段落时同时移除其标签或手输列表符号且不吞掉同段其他字段和固定说明"""
    prefix, suffix = text[:start].strip(), text[end:].strip()
    marker = r"(?:[•●○▪▫◆◇·\-–—*]|\d+[.)、])?\s*"
    if not suffix and re.fullmatch(marker + r"(?:[^:：\n]{1,50}[:：]\s*)?", prefix):
        return 0, len(text)
    return start, end


def empty_field_paragraph(paragraph):
    """空字段可删除自己的列表段落；图片、文本框、域、引用及固定说明必须保留"""
    if paragraph_text(paragraph).strip():
        return False
    protected = {
        w(tag)
        for tag in (
            "drawing",
            "pict",
            "object",
            "fldChar",
            "footnoteReference",
            "endnoteReference",
            "sym",
        )
    }
    return not any(node.tag in protected for node in paragraph.iter())


def fill_fields(nodes: dict, fields: list[TextBinding], values: dict):
    """保留样式替换引文并按顺序分配亮点；返回所有失去内容且可安全收起的字段段落"""
    grouped = {}
    field_counts = Counter(field.node for field in fields)
    order = {identifier: index for index, identifier in enumerate(nodes)}
    highlight_fields = sorted(
        [field for field in fields if field.target == "highlights"],
        key=lambda field: (
            order[field.node],
            quote_range(paragraph_text(nodes[field.node]), field),
        ),
    )
    for binding in fields:
        node = nodes[binding.node]
        start, end = quote_range(paragraph_text(node), binding)
        value = str(values.get(binding.target, ""))
        if binding.target == "highlights" and "_highlight_items" in values:
            position = highlight_fields.index(binding)
            # 位置不足时将余下亮点合并到最后一处；位置过多时不重复填充整组内容
            stop = position + 1 if position < len(highlight_fields) - 1 else None
            value = "\n".join(values["_highlight_items"][position:stop])
        if not value.strip():
            start, end = hidden_personal_range(paragraph_text(node), binding.target, start, end)
            if values.get("_body_ordered"):
                start, end = empty_project_range(paragraph_text(node), fields, binding, start, end)
            if binding.target in ENTRY_TARGETS and field_counts[binding.node] == 1:
                start, end = empty_entry_range(paragraph_text(node), start, end)
        if value and not binding.quote and binding.target.startswith("personal.custom:"):
            value = binding.target.partition(":")[2] + "：" + value
        colon = binding.quote.find("：")
        replacement_colon = value.find("：")
        if binding.target == "highlights" and 0 < colon < 40 and replacement_colon > 0:
            # 标题和正文常使用不同字重且不能把整条亮点塞进原来的粗体标题运行
            grouped.setdefault(binding.node, []).extend(
                [
                    (start, start + colon + 1, value[: replacement_colon + 1]),
                    (start + colon + 1, end, value[replacement_colon + 1 :]),
                ]
            )
        else:
            value += metadata_separator(node, binding, fields, values)
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
            # 清除被整段引文覆盖的旧换行和制表符以免旧样本空行留在新正文中
            position = 0
            for child in list(paragraph.iter()):
                if next(child.iterancestors(w("p")), None) is not paragraph:
                    continue
                if child.tag == w("t"):
                    position += len(child.text or "")
                elif child.tag in {w("br"), w("cr"), w("tab")} and start < position < end:
                    child.getparent().remove(child)
            texts = paragraph_texts(paragraph)
            position, preferred = 0, None
            for text in texts:
                original = text.text or ""
                limit = position + len(original)
                if position < end and start < limit:
                    if preferred is None:
                        preferred = text
                    if original[max(0, start - position) : end - position].strip():
                        preferred = text
                        break
                position = limit
            position = 0
            for text in texts:
                original = text.text or ""
                limit = position + len(original)
                if position < end and start < limit:
                    link = next(text.iterancestors(w("hyperlink")), None)
                    if link is not None:
                        modified_links.add(link)
                    prefix = original[: max(0, start - position)]
                    suffix = original[max(0, end - position) :]
                    set_text(text, prefix + (value if text is preferred else "") + suffix)
                position = limit
        for link in modified_links:
            if next(link.iterancestors(w("p")), None) is not paragraph:
                continue
            parent = link.getparent()
            for child in list(link):
                parent.insert(parent.index(link), child)
            parent.remove(link)
    return [nodes[key] for key in grouped if empty_field_paragraph(nodes[key])]


def region_values(record, fields):
    """项目综合正文只补充未单独安排的资料以免与技术栈、角色或亮点重复"""
    targets = {field.target for field in fields}
    if "_highlight_items" not in record or "details" not in targets:
        return record
    content = {
        "stack": f"技术栈：{record['stack']}" if record["stack"] else "",
        "role": f"担任角色：{record['role']}" if record["role"] else "",
        "description": record["description"],
        "custom_fields": record["custom_fields"],
        "highlights": record["highlights"],
    }
    if "subtitle" in targets:
        targets.add("role")
    return {
        **record,
        "details": "\n".join(
            value for target, value in content.items() if target not in targets and value
        ),
    }


def remove_node(node):
    """删除文字区域或图片容器；保留相邻段落与表格结构"""
    if node.tag in IMAGE_TAGS:
        node = image_container(node)
    node.getparent().remove(node)


def fill_photo(package: TemplatePackage, identifier: str, photo: str):
    """更换选定图片关系并沿用照片框尺寸；隐藏照片时仅移除该图片"""
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
    picture = image_container(node)
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
    """移除已不再使用的旧照片和链接资源；保留其他部件仍在引用的装饰图片"""
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
    """用空段落保存一次分节设置；使删去的内容不改变相邻区域的页面排版"""
    paragraph = etree.Element(w("p"))
    etree.SubElement(paragraph, w("pPr")).append(deepcopy(properties))
    return paragraph


def remove_preserving_sections(node, compact_table=False):
    """保留被删除内容的分栏和分节边界；空字段所在表格行完全腾空时同时收起"""
    parent = node.getparent()
    row = parent.getparent() if parent is not None and parent.tag == w("tc") else None
    if parent is not None:
        position = parent.index(node)
        for boundary in node.iter(w("br")):
            if boundary.get(w("type")) == "column":
                marker = etree.Element(w("p"))
                etree.SubElement(marker, w("r")).append(deepcopy(boundary))
                parent.insert(position, marker)
                position += 1
        for properties in node.iter(w("sectPr")):
            parent.insert(position, section_marker(properties))
            position += 1
    remove_node(node)
    if compact_table and row is not None and row.tag == w("tr"):
        if not any(child.tag != w("tcPr") for cell in row.findall(w("tc")) for child in cell):
            remove_node(row)


def close_empty_tail(package):
    """删除末尾已清空栏目的空节；沿用最后有内容区域的页面设置以免产生空白页"""
    body = package.parts["word/document.xml"].find(w("body"))
    if body is None or not len(body) or body[-1].tag != w("sectPr"):
        return
    trailing, properties = [], None
    for block in reversed(list(body)[:-1]):
        if block.tag != w("p") or block.xpath(
            ".//w:t[normalize-space()] | .//w:drawing | .//w:pict | .//w:object | .//w:br "
            "| .//w:fldChar | .//w:footnoteReference | .//w:endnoteReference",
            namespaces=NS,
        ):
            break
        trailing.append(block)
        section = block.find("w:pPr/w:sectPr", NS)
        if section is not None:
            properties = section
            break
    if properties is not None:
        body.replace(body[-1], deepcopy(properties))
        for block in trailing:
            body.remove(block)


def fill_template(
    source: Path, output: Path, plan: TemplatePlan, content: dict, projects: list[dict]
) -> list[str]:
    """按已核对模板填充；自动扩展个人资料及普通栏目；预览与导出共用排版规则"""
    package = TemplatePackage(source)
    review = package.review(plan)
    if not review["ready"]:
        raise Problem(
            "模板映射尚未完成：" + "；".join(review["errors"] or ["还有未处理的原文或图片"])
        )
    document = ResumeDocument.model_validate(content)
    package, plan, notices = complete_template(package, plan, document, projects)
    missing = missing_targets(document, plan, projects)
    if missing:
        raise Problem("模板未覆盖这些已填写资料，请补充映射或在资料中隐藏：" + "、".join(missing))
    # 已核对的删除必须先落地，避免 PDF 页首重排把旧占位或弃用图形当作未映射内容。
    for identifier in plan.remove:
        remove_preserving_sections(package.node(identifier))
    values = personal_values(document)
    records_by_section = {
        section.title: section_records(document, section.title, projects)
        for section in document.sections
    }
    layout = TemplateLayout(package, plan, document, records_by_section, values)
    personal = PersonalLayout(package, layout.fields, values)
    pdf_header = PDFHeaderLayout(package, plan, values)
    styles = ParagraphStyles(package)
    fill_fields(package.nodes, layout.fields, {**values, **layout.values})
    fill_fields(personal.nodes, personal.fields, values)
    fill_fields(pdf_header.nodes, pdf_header.fields, values)
    for region in plan.repeats:
        original = package.region(region.start, region.end)
        sample = package.region(region.sample_start, region.sample_end)
        parent, position = original[0].getparent(), original[0].getparent().index(original[0])
        records = [
            region_values(record, region.fields)
            for record in section_records(document, region.section, projects)
        ]
        has_sections = any(list(node.iter(w("sectPr"))) for node in sample)
        closing = (
            effective_section(sample[0])
            if not has_sections and any(list(node.iter(w("sectPr"))) for node in original)
            else None
        )
        # 多栏标题和单栏正文同属一条经历；每条复制结束时闭合原有连续分节
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
                if old in package.ids
            }
            for clone in clones:
                # 复制样本时不复制书签身份以免不同记录共享同一个 Word 锚点
                for bookmark in list(clone.iter(w("bookmarkStart"), w("bookmarkEnd"))):
                    bookmark.getparent().remove(bookmark)
                parent.insert(position, clone)
                position += 1
            fields, blank_slots = prepare_project_slots(nodes, region.fields, record, plan.keep)
            align_record(styles, nodes, fields)
            fields = prepare_record_columns(styles, nodes, fields, records, package.nodes)
            record, blank_labels = arrange_project_body(nodes, fields, record, styles)
            blank_fields = fill_fields(nodes, fields, record)
            for blank in dict.fromkeys([*blank_slots, *blank_labels, *blank_fields]):
                remove_preserving_sections(blank, compact_table=True)
            position = parent.index(original[0])
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
        elif closing is not None:
            # 样本外的旧记录可能结束当前页面设置；删除它们时仍须闭合样本所属的节
            parent.insert(position, section_marker(closing))
        for node in original:
            parent.remove(node)
    values = personal_values(document)
    for identifier in plan.photos:
        fill_photo(package, identifier, values["personal.photo"])
    layout.apply()
    personal.apply()
    pdf_header.apply()
    fit_pdf_titles(package, layout.fields)
    close_empty_tail(package)
    drawing_id = 0
    control_id = 0
    for root in package.parts.values():
        clear_pdf_metadata(root)
        for table in list(root.iter(w("tbl"))):
            if not any(
                next(row.iterancestors(w("tbl")), None) is table for row in table.iter(w("tr"))
            ):
                remove_node(table)
        for cell in root.iter(w("tc"), w("txbxContent")):
            if not len(cell) or cell[-1].tag != w("p"):
                etree.SubElement(cell, w("p"))
        # 组合子图形与外层绘图共享编号空间；单独重编号外层会碰撞并导致 Word 无法打开
        for drawing in root.xpath(".//*[local-name()='docPr' or local-name()='cNvPr']"):
            drawing_id += 1
            drawing.set("id", str(drawing_id))
        for control in root.xpath(".//w:sdtPr/w:id", namespaces=NS):
            control_id += 1
            control.set(w("val"), str(control_id))
    clean_resources(package)
    package.write(output)
    return [*notices, *layout.notices, *pdf_header.notices]
