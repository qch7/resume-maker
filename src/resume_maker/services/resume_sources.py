"""来源注册表统一验证内容并同步已确认条目，不删除缺包资料"""

from copy import deepcopy

from resume_maker.core.errors import Problem
from resume_maker.sdk.manifest import compatible
from resume_maker.sdk.sources import ResumeSource, SourceItem, SourcePage


class ResumeSources:
    """来源拥有内容，简历拥有编排、显隐和最后确认快照"""

    def __init__(self, db, contributions):
        """注入事务提供方和可撤销集合，不依赖具体资料库"""
        self.db, self.contributions = db, contributions

    def entries(self):
        """拒绝无效接口、重复标识和不兼容版本"""
        entries = {}
        for item in self.contributions("resume.sources"):
            value = item.value
            if (
                not isinstance(value, ResumeSource)
                or not item.identifier.startswith(item.owner + "/")
                or item.identifier in entries
                or not compatible(value.api_version, ">=1.0.0 <2.0.0")
                or not value.title
                or len(value.title) > 100
                or not callable(value.browse)
                or not callable(value.resolve)
            ):
                raise Problem(f"资料来源协议无效：{item.identifier}", 409)
            entries[item.identifier] = item
        return entries

    def describe(self):
        """返回当前可选资料库，不向客户端传递执行入口"""
        return [
            {
                "id": item.identifier,
                "owner": item.owner,
                "title": item.value.title,
                "version": item.value.version,
            }
            for item in self.entries().values()
        ]

    def browse(self, identifier, cursor=None, query="", limit=50):
        """验证游标和单页内容后返回独立副本"""
        item = self.entries().get(identifier)
        if item is None:
            raise Problem("资料来源未启用，已经采用的内容仍保留。", 409)
        if not 1 <= limit <= 100 or len(query) > 200 or len(cursor or "") > 1000:
            raise Problem("资料查询超出允许范围。")
        with self.db.connect() as conn:
            conn.execute("BEGIN")
            reader = self.db.read_session(conn)
            try:
                page = item.value.browse(reader, cursor, query, limit)
                page = SourcePage.model_validate(page)
                if len(page.items) > limit or len({row.id for row in page.items}) != len(
                    page.items
                ):
                    raise Problem("资料来源返回重复或超量条目。", 409)
                return page.model_dump(mode="json")
            finally:
                reader.close()

    def resolve(self, document, conn=None):
        """仅刷新明确关联的来源字段，来源缺失和未核对时保留原值"""
        if not document:
            return document
        if conn is None:
            with self.db.connect() as connection:
                connection.execute("BEGIN")
                return self.resolve(document, connection)
        result = deepcopy(document)
        for identifier, item in self.entries().items():
            matched = []
            for section in result["sections"]:
                for entry in section.get("entries", []):
                    link = entry.get("source")
                    if link and link.get("provider") == identifier:
                        matched.append((entry, link["id"]))
            if not matched:
                continue
            identifiers = tuple(dict.fromkeys(key for _, key in matched))
            reader = self.db.read_session(conn)
            try:
                rows = tuple(item.value.resolve(reader, identifiers))
            finally:
                reader.close()
            if len(rows) > len(identifiers):
                raise Problem("资料来源返回了未请求的条目。", 409)
            values = {}
            for raw in rows:
                row = SourceItem.model_validate(raw)
                if row.id not in identifiers or row.id in values:
                    raise Problem("资料来源身份不符合请求。", 409)
                values[row.id] = row
            for entry, key in matched:
                if key in values:
                    merge_entry(entry, identifier, values[key])
        return result


def merge_entry(entry, provider, item):
    """同步来源拥有的值，保留手工字段、条目顺序及每份简历的显隐"""
    for key in ("title", "subtitle", "period", "details"):
        entry[key] = getattr(item, key)
    custom = entry.setdefault("custom_fields", [])
    by_id = {field["id"]: field for field in custom}
    definitions = {field["id"]: field for field in entry.get("field_definitions") or []}
    if len({field.id for field in item.custom_fields}) != len(item.custom_fields):
        raise Problem("资料来源字段标识重复。", 409)
    for field in item.custom_fields:
        label = definitions.get(field.id, {}).get("label", field.label)
        if field.id in by_id:
            by_id[field.id].update(label=label, value=field.value)
        else:
            custom.append({**field.model_dump(), "label": label})
    entry["source"] = {"provider": provider, "id": item.id, "version": item.version}
