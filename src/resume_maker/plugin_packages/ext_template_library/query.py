"""插件拥有的工作台查询贡献"""

from resume_maker.infrastructure.database import unpack
from resume_maker.sdk.storage import database_query


@database_query
def templates(conn, state):
    """发布可复用模板引用摘要"""
    state["templates"] = [
        unpack(row)
        for row in conn.execute(
            "SELECT id,name,created_at FROM templates "
            "WHERE json_type(mapping_json,'$.plan')='object' ORDER BY created_at DESC"
        )
    ]
