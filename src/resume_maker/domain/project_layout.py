"""版本内的项目正文顺序；兼容旧版简历设置；标题与时间独立保留在顶部"""

from resume_maker.domain.models import ProjectVisibility


def project_body_order(content: dict, settings: ProjectVisibility | None = None) -> list[str]:
    """按保存位置排列可用字段；新增项追加；删除项不挤占剩余条目的相对顺序"""
    defaults = ["role", "stack", "description", "highlights"]
    defaults.extend(f"custom:{field['id']}" for field in content.get("custom_fields", []))
    order = content.get("body_order")
    if order is None:
        order = settings.order if settings else []
    return [key for key in dict.fromkeys([*order, *defaults]) if key in defaults]


def project_body_entries(content: dict, selected: list[str], settings=None) -> list[dict]:
    """输出已应用显隐的有内容条目；亮点作为一组移动；组内顺序仍由亮点编排控制"""
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
