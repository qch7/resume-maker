"""经历版本保存正文顺序，未指定时采用简历编排，标题、时间固定在顶部"""

from resume_maker.domain.models import ProjectVisibility


def project_body_order(content: dict, settings: ProjectVisibility | None = None) -> list[str]:
    """按保存位置排列字段，追加新增项，保留其余条目的相对顺序"""
    defaults = ["role", "stack", "description", "highlights"]
    defaults.extend(f"custom:{field['id']}" for field in content.get("custom_fields", []))
    order = content.get("body_order")
    if order is None:
        order = settings.order if settings else []
    return [key for key in dict.fromkeys([*order, *defaults]) if key in defaults]


def project_body_entries(content: dict, selected: list[str], settings=None) -> list[dict]:
    """仅输出可见且有内容的条目，亮点整组移动，组内沿用亮点编排顺序"""
    custom = {f"custom:{field['id']}": field for field in content.get("custom_fields", [])}
    points = {point["id"]: point for point in content["highlights"]}
    entries = []
    for key in project_body_order(content, settings):
        if key == "highlights":
            entries.extend(
                {
                    "key": key,
                    "label": points[identifier]["title"],
                    "text": points[identifier]["text"],
                }
                for identifier in selected
            )
            continue
        if key in custom:
            field = custom[key]
            if not field["visible"] or not field["label"].strip() or not field["value"].strip():
                continue
            label, text = field["label"].strip(), field["value"].strip()
        else:
            label = {"role": "担任角色", "stack": "技术栈", "description": "项目描述"}[key]
            text = "、".join(content[key]) if key == "stack" else content[key]
        if text.strip():
            entries.append({"key": key, "label": label, "text": text})
    return entries
