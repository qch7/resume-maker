"""整理模板使用的可见资料并校验当前内容所需的填写位置"""

from resume_maker.core.errors import Problem
from resume_maker.domain.experience import displayed_experience
from resume_maker.domain.models import CustomInfoField
from resume_maker.domain.project_layout import project_body_entries
from resume_maker.domain.resume import ResumeDocument
from resume_maker.domain.templates import TemplatePlan
from resume_maker.integrations.word.full_resume import displayed_entries, visible_custom_fields


def custom_text(fields) -> str:
    """按用户顺序输出可见自定义信息且不输出空名称或空值"""
    return "\n".join(f"{field.label}：{field.value}" for field in visible_custom_fields(fields))


def section_records(document: ResumeDocument, title: str, projects: list[dict]) -> list[dict]:
    """按栏目名称取可见记录；项目区始终使用用户选定的固定经历版本"""
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
            settings = document.project_visibility.get(project.get("project_id", ""))
            value = displayed_experience(project["content"], settings, section.field_definitions)
            custom = custom_text(
                [CustomInfoField.model_validate(field) for field in value["custom_fields"]]
            )
            points = {point["id"]: point for point in value["highlights"]}
            highlight_items = [
                f"{points[identifier]['title']}：{points[identifier]['text']}"
                for identifier in project["highlight_ids"]
            ]
            highlights = "\n".join(highlight_items)
            stack = "、".join(value["stack"])
            details = "\n".join(
                filter(
                    None,
                    [
                        f"技术栈：{stack}" if stack else "",
                        f"担任角色：{value['role']}" if value["role"] else "",
                        value["description"],
                        custom,
                        highlights,
                    ],
                )
            )
            records.append(
                {
                    **value,
                    "stack": stack,
                    "highlights": highlights,
                    "_highlight_items": highlight_items,
                    "details": details,
                    "subtitle": value["role"],
                    "custom_fields": custom,
                    "_body_entries": project_body_entries(
                        value, project["highlight_ids"], settings
                    ),
                    "_body_ordered": value.get("body_order") is not None
                    or bool(settings and settings.order),
                }
            )
        return records
    return [
        {**entry.model_dump(), "custom_fields": custom_text(entry.custom_fields)}
        for entry in displayed_entries(section)
    ]


def personal_values(document: ResumeDocument) -> dict[str, str]:
    """将资料字段转为替换值；隐藏字段清空；照片由独立图片映射处理"""
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


def required_entry_fields(records: list[dict], *, project: bool) -> list[str]:
    """为 AI 识别与覆盖校验提供同一份非空字段要求；隐藏资料已由记录整理阶段移除"""
    fields = (
        ("title", "period", "role", "stack", "description", "highlights", "custom_fields")
        if project
        else ("title", "subtitle", "period", "details", "custom_fields")
    )
    return [field for field in fields if any(record.get(field) for record in records)]


def missing_targets(
    document: ResumeDocument, plan: TemplatePlan, projects: list[dict]
) -> list[str]:
    """列出当前非空资料缺少的位置以防导出时静默丢失姓名、栏目或照片"""
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
            required = required_entry_fields(records, project=section.kind == "projects")
            if section.kind == "projects" and "details" in bound:
                bound |= {"role", "stack", "description", "highlights", "custom_fields"}
            for field in required:
                if field not in bound:
                    missing.append(f"{section.title} · {field}")
    return list(dict.fromkeys(missing))
