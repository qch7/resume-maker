"""简历读取、保存和生成共用的荣誉资料解析入口"""

from resume_maker.domain.honor_entries import sync_honor_document
from resume_maker.infrastructure.database import dump, now, unpack


def honor_sources(conn):
    """返回同步和排序所需资料；工作台轮询不携带附件文本或识别原文"""
    rows = conn.execute("SELECT value_json FROM settings WHERE key LIKE 'honor:%'")
    return [
        {
            **{key: item[key] for key in ("id", "fields", "reviewed", "version")},
            "updated_at": item.get("updated_at", ""),
        }
        for row in rows
        for item in [unpack(row)["value"]]
    ]


def resolve_honor_document(db, document, conn=None):
    """在给定事务内或独立读连接中取得最新荣誉且不修改原始简历对象"""
    if not document:
        return document
    if conn is None:
        with db.connect() as connection:
            return resolve_honor_document(db, document, connection)
    return sync_honor_document(document, honor_sources(conn))


def preserve_deleted_honor(conn, honor):
    """删除来源前将最后核对资料留在关联简历中；历史导出文件保持原样"""
    rows = conn.execute("SELECT id,document_json FROM resumes WHERE document_json IS NOT NULL")
    for row in rows.fetchall():
        resume = unpack(row)
        updated = sync_honor_document(resume["document"], [honor])
        if updated != resume["document"]:
            conn.execute(
                "UPDATE resumes SET document_json=?,version=version+1,updated_at=? WHERE id=?",
                (dump(updated), now(), resume["id"]),
            )
