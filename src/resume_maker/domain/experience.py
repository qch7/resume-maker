"""经历字段读取、替换与校验：纯数据操作，不产生数据库或文件副作用。"""

from copy import deepcopy

from resume_maker.core.errors import Problem
from resume_maker.domain.models import DefaultField, Experience, Highlight, ProjectVisibility
from resume_maker.domain.project_layout import project_body_order


def same_experience(left: dict, right: dict) -> bool:
    """比较规范化内容；明确排序与继承旧简历排序不同，两个明确排序比较实际位置。"""
    values = []
    for content in (left, right):
        normalized = Experience.model_validate(content).model_dump()
        if normalized["body_order"] is not None:
            normalized["body_order"] = project_body_order(normalized)
        values.append(normalized)
    return values[0] == values[1]


def field_value(content: dict, field: str):
    """按整段、元信息、顺序或亮点标识读取经历字段。"""
    if field == "experience":
        return content
    if field == "meta":
        return {k: v for k, v in content.items() if k != "highlights"}
    if field == "order":
        return [h["id"] for h in content["highlights"]]
    if field.startswith("highlight:"):
        return next((h for h in content["highlights"] if h["id"] == field[10:]), None)
    raise Problem("未知编辑字段")


def replace_field(content: dict, field: str, value) -> dict:
    """在深拷贝上替换指定字段，并校验亮点内容及完整排序。"""
    content = deepcopy(content)
    if field == "experience":
        # 旧客户端或历史 AI 建议未提供扩展资料时，保留用户已有的条目与显隐设置。
        preserved = {
            key: content[key]
            for key in ("hidden_fields", "custom_fields", "body_order")
            if key in content
        }
        return Experience.model_validate({**preserved, **value}).model_dump()
    if field == "meta":
        content.update({k: v for k, v in value.items() if k != "highlights"})
    elif field == "order":
        by_id = {h["id"]: h for h in content["highlights"]}
        if set(value) != set(by_id) or len(value) != len(by_id):
            raise Problem("排序必须包含所有亮点且不能重复。")
        content["highlights"] = [by_id[i] for i in value]
    elif field.startswith("highlight:"):
        point_id = field[10:]
        items = content["highlights"]
        index = next((i for i, h in enumerate(items) if h["id"] == point_id), len(items))
        if value is None:
            content["highlights"] = [h for h in items if h["id"] != point_id]
        else:
            value = Highlight.model_validate({**value, "id": point_id}).model_dump()
            if index == len(items):
                items.insert(0, value)
            else:
                items[index] = value
    else:
        raise Problem("未知编辑字段")
    return Experience.model_validate(content).model_dump()


def displayed_experience(
    content: dict,
    visibility: ProjectVisibility | None = None,
    definitions: list[DefaultField] | None = None,
) -> dict:
    """先应用当前简历的显隐覆盖，再清空排版副本，兼容旧版本自带的显隐设置。"""
    value = Experience.model_validate(content).model_dump()
    hidden = set(value["hidden_fields"])
    configured = {field.id: field for field in definitions} if definitions is not None else None
    if configured is not None:
        for key in ("title", "period", "role", "stack", "description"):
            if key not in configured or not configured[key].visible:
                hidden.add(key)
        for field in value["custom_fields"]:
            definition = configured.get(field["id"])
            if definition:
                field.update(label=definition.label, visible=definition.visible)
            elif field["id"].startswith("default:"):
                field["visible"] = False
    if visibility:
        for field, visible in visibility.fields.items():
            if visible:
                hidden.discard(field)
            else:
                hidden.add(field)
        for field in value["custom_fields"]:
            field["visible"] = visibility.custom_fields.get(field["id"], field["visible"])
    if configured is not None:
        # 已删除的默认项不能被旧的单份简历显隐覆盖重新打开。
        hidden.update(
            key
            for key in ("title", "period", "role", "stack", "description")
            if key not in configured
        )
        for field in value["custom_fields"]:
            if field["id"].startswith("default:") and field["id"] not in configured:
                field["visible"] = False
    for field in hidden:
        value[field] = [] if field == "stack" else ""
    return value
