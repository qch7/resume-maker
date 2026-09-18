"""为已识别完整、但缺少个人文字资料位置的模板补出可复用填写段落"""

from copy import deepcopy
from io import BytesIO

from lxml import etree

from resume_maker.core.errors import Problem
from resume_maker.domain.templates import TextBinding
from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.templates.contact_style import (
    SLOT_VERSION,
    inherit_contact_runs,
    labelled_contact,
)
from resume_maker.integrations.word.templates.flow import flow_paragraph
from resume_maker.integrations.word.templates.layout import child_in
from resume_maker.integrations.word.templates.mapping import (
    TemplatePackage,
    paragraph_text,
)
from resume_maker.integrations.word.templates.values import missing_targets, personal_values

PERSONAL_LABELS = {
    "personal.name": "姓名",
    "personal.job_title": "求职意向",
    "personal.gender": "性别",
    "personal.age": "年龄",
    "personal.phone": "电话",
    "personal.email": "邮箱",
    "personal.gpa": "专业成绩",
    "personal.location": "所在地",
    "personal.website": "个人主页",
}
PLACEHOLDER = "〔待填写〕"
CONTACT_FIELDS = {"personal.phone", "personal.email", "personal.location", "personal.website"}


def personal_insertion(package, plan, document):
    """在首栏目之前沿用联系段落或可扩展单元格且不把个人资料插进重复记录和固定框"""
    body = package.parts["word/document.xml"].find(w("body"))
    blocks = list(body)
    headings = {section.title for section in document.sections} | {"项目经历"}
    section_nodes = [region.start for region in plan.repeats]
    section_nodes.extend(
        field.node for field in plan.fields if field.target.startswith("section-title:")
    )
    section_nodes.extend(
        identifier
        for identifier in plan.keep
        if paragraph_text(package.node(identifier)).strip().rstrip("：:") in headings
    )
    boundary = min(
        (
            blocks.index(child_in(package.node(identifier), body))
            for identifier in section_nodes
            if body in package.node(identifier).iterancestors()
        ),
        default=len(blocks) - (bool(blocks) and blocks[-1].tag == w("sectPr")),
    )
    personal = [
        package.node(field.node) for field in plan.fields if field.target.startswith("personal.")
    ]
    preceding = [
        (blocks.index(child_in(node, body)), node)
        for node in personal
        if body in node.iterancestors() and blocks.index(child_in(node, body)) < boundary
    ]
    if preceding:
        contacts = {
            package.node(field.node)
            for field in plan.fields
            if field.target in CONTACT_FIELDS and field.quote
        }
        sequence = {node: index for index, node in enumerate(package.nodes.values())}
        labelled = {
            node
            for _, node in preceding
            if labelled_contact(
                node, [field for field in plan.fields if package.node(field.node) is node]
            )
            is not None
        }
        position, donor = max(
            preceding,
            key=lambda pair: (
                pair[1] in contacts and pair[1] in labelled,
                pair[1] in contacts,
                bool(paragraph_text(pair[1]).strip()),
                pair[0],
                sequence[pair[1]],
            ),
        )
        container = donor.getparent()
        row = next(donor.iterancestors(w("tr")), None)
        fixed = row.find("w:trPr/w:trHeight", NS) if row is not None else None
        if (
            donor in contacts
            and container.tag == w("tc")
            and (fixed is None or fixed.get(w("hRule")) != "exact")
            and not any(
                container is node or container in node.iterancestors()
                for region in plan.repeats
                for node in package.region(region.start, region.end)
            )
        ):
            return container, container.index(donor) + 1, donor
        return body, position + 1, donor
    return body, boundary, personal[-1] if personal else None


def remap_plan(plan, previous, package):
    """按原 XML 节点身份更新全部引用；新增段落不能让照片、栏目或引文指向别处"""
    updated = plan.model_copy(deep=True)
    for field in updated.fields:
        field.node = package.ids[previous[field.node]]
    for region in updated.repeats:
        for key in ("start", "end", "sample_start", "sample_end"):
            setattr(region, key, package.ids[previous[getattr(region, key)]])
        for field in region.fields:
            field.node = package.ids[previous[field.node]]
    for key in ("photos", "keep", "remove"):
        setattr(updated, key, [package.ids[previous[node]] for node in getattr(updated, key)])
    return updated


def loose_contact_fields(package, plan, body, donor):
    """个人资料区内无标签空位统一回到联系方式；前后留白都不能直接输出孤立的值"""
    if donor is None or donor.getparent() is not body:
        return []
    if not any(
        field.target in CONTACT_FIELDS and field.quote and package.node(field.node) is donor
        for field in plan.fields
    ):
        return []
    boundaries = [region.start for region in plan.repeats]
    boundaries.extend(
        field.node
        for field in plan.fields
        if field.target.startswith("section-title:")
        or field.target in {"personal.job_title", "personal.gpa"}
    )
    boundary = min(
        (
            body.index(child_in(package.node(identifier), body))
            for identifier in boundaries
            if body in package.node(identifier).iterancestors()
            and body.index(child_in(package.node(identifier), body)) > body.index(donor)
        ),
        default=len(body),
    )
    loose = []
    for field in plan.fields:
        node = package.node(field.node)
        if (
            field.target not in CONTACT_FIELDS
            or field.quote
            or node.getparent() is not body
            or body.index(node) >= boundary
            or paragraph_text(node).strip()
            or node.xpath(
                "w:pPr/w:framePr | w:pPr/w:sectPr | w:pPr/w:pBdr | w:pPr/w:shd | w:pPr/w:numPr",
                namespaces=NS,
            )
        ):
            continue
        preceding = node.getprevious()
        label = PERSONAL_LABELS[field.target]
        if preceding is not None:
            # 带图标或边框的空位可能是模板有意安排的资料区域且不能仅因没有文字标签移动它
            if preceding.xpath(".//w:drawing | .//w:pict", namespaces=NS):
                continue
            literal = paragraph_text(preceding).strip()
            if literal.rstrip("：:") == label or (
                literal.endswith(("：", ":")) and package.ids[preceding] in plan.keep
            ):
                continue
        loose.append(field)
    return loose


def vacant_contact_column(paragraph) -> bool:
    """仅复用显式换行和完整前行共同证明的空列；支持任意列数和字段顺序"""
    if paragraph is None:
        return False
    stops = paragraph.findall("w:pPr/w:tabs/w:tab", NS)
    if not stops or any(stop.get(w("val")) != "left" for stop in stops):
        return False
    if paragraph.find("w:pPr/w:bidi", NS) is not None:
        return False
    if paragraph.xpath(".//w:drawing | .//w:pict | w:pPr/w:framePr", namespaces=NS):
        return False
    previous_tabs, current_tabs, line_breaks, text = 0, 0, 0, ""
    for node in paragraph.iter():
        if next(node.iterancestors(w("p")), None) is not paragraph:
            continue
        if next(node.iterancestors(w("r")), None) is None:
            continue
        if node.tag in {w("br"), w("cr")}:
            if node.get(w("type"), "textWrapping") != "textWrapping":
                return False
            previous_tabs = max(previous_tabs, current_tabs)
            current_tabs, text = 0, ""
            line_breaks += 1
        elif node.tag == w("tab"):
            current_tabs += 1
        elif node.tag == w("t"):
            text += node.text or ""
    return (
        line_breaks > 0
        and previous_tabs == len(stops)
        and current_tabs < len(stops)
        and bool(text.strip())
    )


def append_personal_slot(body, position, donor, label, style_donor=None):
    """沿用联系信息的空右列或段落缩进添加带标签位置且不改变照片留白和原列坐标"""
    paragraph = flow_paragraph(f"{label}：{PLACEHOLDER}", donor)
    inherit_contact_runs(paragraph, style_donor, label, PLACEHOLDER)
    paragraph.set(SLOT_VERSION, "1")
    if donor is not None and donor.getparent() is body and vacant_contact_column(donor):
        run = paragraph.find(w("r"))
        run.insert(1 if run.find(w("rPr")) is not None else 0, etree.Element(w("tab")))
        donor.extend(paragraph.findall(w("r")))
        return donor, position
    if donor is not None and donor.getparent() is body:
        # 新行与同一资料区域的样本沿用缩进、制表位和行距且不继承绝对定位或分节
        properties = paragraph.find(w("pPr"))
        for tag in ("ind", "tabs", "spacing", "jc"):
            original = donor.find(f"w:pPr/w:{tag}", NS)
            if original is not None:
                current = properties.find(w(tag))
                if current is not None:
                    properties.remove(current)
                properties.append(deepcopy(original))
    body.insert(position, paragraph)
    return paragraph, position + 1


def supplement_personal_fields(package, plan, document, projects, source=None):
    """在独立副本补齐个人文字位置；识别阶段可保存快照；填充时仅在内存扩展"""
    if not package.review(plan)["ready"]:
        return package, plan, []
    body, _, donor = personal_insertion(package, plan, document)
    values = personal_values(document)
    loose = [
        field
        for field in loose_contact_fields(package, plan, body, donor)
        if values.get(field.target)
    ]
    # 旧版自动生成的位置有可验证的占位符；重建它们即可让已保存模板也获得样式修复
    legacy = [
        field
        for field in plan.fields
        if field.quote == PLACEHOLDER
        and not package.node(field.node).get(SLOT_VERSION)
        and paragraph_text(package.node(field.node)).strip()
        == PERSONAL_LABELS.get(field.target, field.target.partition(":")[2]) + "：" + PLACEHOLDER
        and sum(other.node == field.node for other in plan.fields) == 1
        and field.node not in {*plan.keep, *plan.remove}
    ]
    base = plan.model_copy(deep=True)
    base.fields = [field for field in base.fields if field not in [*loose, *legacy]]
    try:
        missing = [
            target
            for target in missing_targets(document, base, projects)
            if target in PERSONAL_LABELS or target.startswith("personal.custom:")
        ]
    except Problem:
        return package, plan, []
    # 栏目、照片等缺项继续由完整校验报告且不能阻止可独立完成的个人文字补位
    if not missing:
        return package, plan, []
    labels = [PERSONAL_LABELS.get(target, target.partition(":")[2]) for target in missing]
    # 先在完整副本中新增并校验；预览和导出不能修改已保存的模板及映射
    buffer = BytesIO()
    package.write(buffer)
    working = TemplatePackage(buffer)
    previous = dict(working.nodes)
    for field in legacy:
        node = working.node(field.node)
        node.getparent().remove(node)
    body, position, donor = personal_insertion(working, base, document)
    style_donor = (
        labelled_contact(
            donor, [field for field in base.fields if working.node(field.node) is donor]
        )
        if donor is not None
        else None
    )
    added = []
    for label in labels:
        paragraph, position = append_personal_slot(body, position, donor, label, style_donor)
        added.append((paragraph, paragraph_text(paragraph).count(PLACEHOLDER)))
    working.reindex()
    updated = remap_plan(base, previous, working)
    updated.fields.extend(
        TextBinding(node=working.ids[node], quote=PLACEHOLDER, target=target, occurrence=occurrence)
        for (node, occurrence), target in zip(added, missing, strict=True)
    )
    if len(updated.fields) > 150 or not working.review(updated)["ready"]:
        return package, plan, []
    updated.warnings = [
        warning for warning in updated.warnings if not any(target in warning for target in missing)
    ]
    notice = (
        "已将" + "、".join(labels) + "调整到联系方式区，补上标签并沿用原有对齐。"
        if loose
        else "已在个人资料区自动补充" + "、".join(labels) + "的填写位置。"
    )
    updated.summary = "已保留原有资料、栏目和照片映射。" + notice
    if source is not None:
        temporary = source.with_name("supplemented.docx")
        working.write(temporary)
        temporary.replace(source)
    working.notices = [*package.notices, notice]
    return working, updated, [notice]
