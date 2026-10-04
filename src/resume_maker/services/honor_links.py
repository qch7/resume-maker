"""简历读取、保存和生成共用的荣誉资料解析入口"""

from resume_maker.sdk.records import unpack


def resume_source():
    """荣誉库通过公开来源契约提供已核对内容，旧条目标识继续可读"""
    from resume_maker.sdk.sources import ResumeSource, SourcePage

    def resolve(reader, identifiers):
        """仅返回本轮明确请求且已经人工核对的荣誉"""
        values = (reader.setting("honor:" + identifier) for identifier in identifiers)
        return tuple(source_item(value) for value in values if value and value["reviewed"])

    def browse(reader, cursor, query, limit):
        """按稳定标识分页，搜索不把证书原文和识别建议传给客户端"""
        rows = reader.all(
            "SELECT value_json FROM settings WHERE key LIKE 'honor:%' "
            "AND json_extract(value_json,'$.reviewed')=1 "
            "AND key>? AND instr(lower(json_extract(value_json,'$.fields.name')),lower(?))>0 "
            "ORDER BY key LIMIT ?",
            (cursor or "", query, limit + 1),
        )
        selected = rows[:limit]
        return SourcePage(
            items=tuple(source_item(row["value"]) for row in selected),
            cursor="honor:" + selected[-1]["value"]["id"] if len(rows) > limit else None,
        )

    return ResumeSource("荣誉库", "1.0.0", browse, resolve, legacy_prefix="honor:")


def source_item(honor):
    """荣誉来源只发布可复用文字，附件仍由文件接口持有"""
    from resume_maker.domain.honor_entries import HONOR_CUSTOM_FIELDS
    from resume_maker.sdk.sources import SourceField, SourceItem

    fields = honor["fields"]
    return SourceItem(
        id=honor["id"],
        version=str(honor["version"]),
        title=fields["name"],
        subtitle=fields["issuer"],
        period=fields["date"],
        details=fields["description"],
        custom_fields=tuple(
            SourceField(id=f"honor-field:{key}", label=label, value=fields[key])
            for key, label in HONOR_CUSTOM_FIELDS.items()
        ),
    )


def honor_sources(conn):
    """返回同步和排序所需资料，工作台轮询不携带附件文本或识别原文"""
    rows = conn.execute("SELECT value_json FROM settings WHERE key LIKE 'honor:%'")
    return [
        {
            **{key: item[key] for key in ("id", "fields", "reviewed", "version")},
            "updated_at": item.get("updated_at", ""),
        }
        for row in rows
        for item in [unpack(row)["value"]]
    ]
