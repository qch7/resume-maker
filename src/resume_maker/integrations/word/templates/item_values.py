"""模板聚合字段保留每条内容的稳定身份，替换文字时同步传递给运行"""

from resume_maker.integrations.word.item_layout import reference


def fragment(text, parts, kind=None):
    """把可见文本绑定到原资料字段，模板目标名称仅用于选择填写位置"""
    return {"text": text, "ref": reference(parts, kind)}


def custom_fragments(fields, prefix):
    """按稳定自定义字段身份生成独立片段，重复标签仍可各自排版"""
    return [
        fragment(
            f"{field.label.strip()}：{field.value.strip()}", (*prefix, "custom", field.id), "custom"
        )
        for field in fields
    ]


def project_fragments(project, record, fields):
    """综合正文及亮点保留逐项引用，项目版本变化不改变样式身份"""
    prefix = ("project", project.get("project_id", ""))
    layout = {
        key: [fragment(record[key], (*prefix, key))]
        for key in ("title", "period", "role", "stack", "description")
    }
    layout["subtitle"] = layout["role"]
    points = {point["id"]: point for point in project["content"]["highlights"]}
    layout["highlights"] = [
        fragment(
            f"{points[key]['title']}：{points[key]['text']}",
            (*prefix, "highlight", key),
            "highlight",
        )
        for key in project["highlight_ids"]
    ]
    layout["custom_fields"] = custom_fragments(fields, prefix)
    layout["details"] = detail_fragments(record, layout, set())
    for entry in record["_body_entries"]:
        key = entry["key"]
        parts = (
            ("highlight", entry["id"])
            if key == "highlights"
            else ("custom", key[7:])
            if key.startswith("custom:")
            else (key,)
        )
        entry["ref"] = reference(
            (*prefix, *parts),
            "highlight" if key == "highlights" else "custom" if key.startswith("custom:") else None,
        )
    return layout


def detail_fragments(record, layout, targets):
    """综合正文只填未单独映射的字段，文字顺序沿用原模板协议"""
    result = []
    for key in ("stack", "role", "description", "custom_fields", "highlights"):
        if key in targets or not record[key]:
            continue
        for item in layout.get(key, []):
            label = {"stack": "技术栈：", "role": "担任角色："}.get(key, "")
            result.append({**item, "text": label + item["text"]})
    return result


def entry_fragments(section, entry):
    """所有栏目条目沿用同一身份模型，保留各字段的独立运行样式"""
    prefix = ("entry", section.id, entry.id)
    layout = {
        key: [fragment(getattr(entry, key), (*prefix, key))]
        for key in ("title", "subtitle", "period", "details")
    }
    layout["custom_fields"] = custom_fragments(entry.custom_fields, prefix)
    return layout


def personal_fragments(document, values):
    """个人字段、栏目标题在映射节点上绑定身份，不在最终文档中按文案定位"""
    layout = {
        f"personal.{key}": [
            fragment(value, ("personal", key), key if key in {"name", "job_title"} else "personal")
        ]
        for key, value in document.personal.model_dump().items()
        if isinstance(value, str) and key != "photo"
    }
    fields = [
        field
        for field in document.personal.custom_fields
        if field.visible and field.label.strip() and field.value.strip()
    ]
    layout["personal.custom_fields"] = custom_fragments(fields, ("personal",))
    for field in fields:
        layout[f"personal.custom:{field.label.strip()}"] = [
            fragment(field.value.strip(), ("personal", "custom", field.id), "custom")
        ]
    for section in document.sections:
        layout[f"section-title:{section.title}"] = [
            fragment(section.title, ("section", section.id, "title"), "section_title")
        ]
    return {target: pieces for target, pieces in layout.items() if values.get(target)}
