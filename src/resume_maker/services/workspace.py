"""工作台在同一读取快照聚合系统资料和已启用插件贡献"""

from resume_maker.infrastructure.database import unpack


class Workspace:
    """系统聚合器只查询经历和简历，业务扩展自行读取所属资料"""

    def __init__(self, catalog, *, contributors=None):
        """贡献读取器由组合根注入，不通过可选模块导入推测能力"""
        self.db = catalog.db
        self.contributors = contributors or (lambda: ())

    def state(self):
        """保持经历活动时间、简历来源和各插件摘要的事务一致性"""
        with self.db.connect() as conn:
            conn.execute("BEGIN")
            state = {
                "resume_defaults": None,
                "projects": [
                    unpack(row)
                    for row in conn.execute(
                        "SELECT p.*, h.parent_id, b.head_revision, MAX(p.updated_at, "
                        "COALESCE((SELECT MAX(updated_at) FROM drafts "
                        "WHERE project_id=p.id), p.updated_at)) AS activity_at "
                        "FROM projects p LEFT JOIN project_hierarchy h ON h.project_id=p.id "
                        "JOIN experience_branches b ON b.project_id=p.id AND b.is_default=1 "
                        "WHERE p.archived=0 ORDER BY p.created_at"
                    )
                ],
                "branches": [
                    unpack(row)
                    for row in conn.execute(
                        "SELECT * FROM experience_branches ORDER BY created_at,id"
                    )
                ],
                "resumes": [
                    unpack(row)
                    for row in conn.execute(
                        "SELECT * FROM resumes WHERE id NOT IN "
                        "(SELECT resume_id FROM resume_deletions) ORDER BY updated_at DESC"
                    )
                ],
                "honors": [],
                "conversations": [],
                "templates": [],
                "jobs": [],
            }
            defaults = unpack(
                conn.execute(
                    "SELECT value_json FROM settings WHERE key='resume_defaults'"
                ).fetchone()
            )
            state["resume_defaults"] = defaults["value"] if defaults else None
            for contribute in self.contributors():
                contribute.value(conn, state)
            return state
