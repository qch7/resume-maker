"""业务插件的工作台查询贡献，共享调用方的读取快照"""

from resume_maker.infrastructure.database import unpack


def conversations(conn, state):
    """提供会话及当前任务摘要，不把后台服务对象传入聚合器"""
    state["conversations"] = [
        unpack(row)
        for row in conn.execute(
            "SELECT * FROM conversations WHERE archived=0 ORDER BY updated_at DESC"
        )
    ]
    for project in state["projects"]:
        project["activity_at"] = max(
            [project["activity_at"]]
            + [
                item["updated_at"]
                for item in state["conversations"]
                if item["project_id"] == project["id"]
            ]
        )
    state["jobs"] = [
        unpack(row)
        for row in conn.execute(
            "SELECT id,project_id,conversation_id,kind,status,error,created_at,finished_at "
            "FROM jobs ORDER BY created_at DESC LIMIT 100"
        )
    ]


def honors(conn, state):
    """已核对的荣誉与简历在同一读取事务同步"""
    from resume_maker.services.honor_links import honor_sources

    state["honors"] = honor_sources(conn)


def templates(conn, state):
    """发布可复用模板引用摘要"""
    state["templates"] = [
        unpack(row)
        for row in conn.execute(
            "SELECT id,name,created_at FROM templates "
            "WHERE json_type(mapping_json,'$.plan')='object' ORDER BY created_at DESC"
        )
    ]
