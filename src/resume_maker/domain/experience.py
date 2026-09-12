"""经历字段读取、替换与校验：纯数据操作，不产生数据库或文件副作用。"""

from copy import deepcopy

from resume_maker.core.errors import Problem
from resume_maker.domain.models import Experience, Highlight


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
        return Experience.model_validate(value).model_dump()
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
                items.append(value)
            else:
                items[index] = value
    else:
        raise Problem("未知编辑字段")
    return Experience.model_validate(content).model_dump()
