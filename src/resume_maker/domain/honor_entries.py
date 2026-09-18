"""共享荣誉内容与简历内独立排版设置之间的无副作用映射"""

from copy import deepcopy

from resume_maker.domain.honors import HonorFields

HONOR_ENTRY_FIELDS = {
    "name": "title",
    "issuer": "subtitle",
    "date": "period",
    "description": "details",
}
HONOR_CUSTOM_FIELDS = {
    "award": "奖项",
    "level": "荣誉级别",
    "recipient": "获奖人",
    "certificate_number": "证书编号",
    "category": "分类",
}
HONOR_CUSTOM_IDS = {f"honor-field:{key}" for key in HONOR_CUSTOM_FIELDS}


def sync_honor_document(document, honors):
    """按稳定来源标识同步已核对资料；保留显隐、排序、备注及没有来源的条目"""
    if not document:
        return document
    sources = {f"honor:{item['id']}": item for item in honors if item["reviewed"]}
    result = deepcopy(document)
    for section in result["sections"]:
        for entry in section.get("entries", []):
            source = sources.get(entry["id"])
            if source is None:
                continue
            fields = HonorFields.model_validate(source["fields"]).model_dump()
            for key, target in HONOR_ENTRY_FIELDS.items():
                entry[target] = fields[key]
            custom = entry.setdefault("custom_fields", [])
            by_id = {item["id"]: item for item in custom}
            definitions = {item["id"]: item for item in entry.get("field_definitions") or []}
            for key, label in HONOR_CUSTOM_FIELDS.items():
                identifier = f"honor-field:{key}"
                label = definitions.get(identifier, {}).get("label", label)
                existing = by_id.get(identifier)
                if existing is not None:
                    existing.update(label=label, value=fields[key])
                else:
                    custom.append(
                        {"id": identifier, "label": label, "value": fields[key], "visible": False}
                    )
    return result
