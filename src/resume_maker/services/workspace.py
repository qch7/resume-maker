"""工作台轮询所需的项目活动时间和资源聚合查询。"""

from resume_maker.services.catalog import Catalog


class Workspace:
    """工作台首屏和轮询需要的聚合查询。"""

    def __init__(self, catalog: Catalog):
        """保存当前模块所需依赖，供后续业务操作共享使用。"""
        self.catalog, self.db = catalog, catalog.db

    def state(self):
        """聚合项目活动时间、会话、简历、模板及最近任务，供工作台轮询。"""
        return {
            "projects": self.db.all(
                "SELECT p.*, h.parent_id, b.head_revision, MAX(p.updated_at, "
                "COALESCE((SELECT MAX(updated_at) FROM drafts "
                "WHERE project_id=p.id), p.updated_at), "
                "COALESCE((SELECT MAX(updated_at) FROM conversations "
                "WHERE project_id=p.id AND archived=0), p.updated_at)) AS activity_at "
                "FROM projects p LEFT JOIN project_hierarchy h ON h.project_id=p.id "
                "JOIN experience_branches b ON b.project_id=p.id AND b.is_default=1 "
                "WHERE p.archived=0 ORDER BY p.created_at"
            ),
            "conversations": self.db.all(
                "SELECT * FROM conversations WHERE archived=0 ORDER BY updated_at DESC"
            ),
            "branches": self.db.all("SELECT * FROM experience_branches ORDER BY created_at,id"),
            "resumes": self.db.all(
                "SELECT * FROM resumes WHERE id NOT IN "
                "(SELECT resume_id FROM resume_deletions) ORDER BY updated_at DESC"
            ),
            "templates": self.db.all(
                "SELECT id,name,created_at,CASE WHEN json_type(mapping_json,'$.plan')='object' "
                "THEN 'adaptive' ELSE 'projects' END AS kind "
                "FROM templates ORDER BY created_at DESC"
            ),
            "jobs": self.db.all(
                "SELECT id,project_id,conversation_id,kind,status,error,created_at,finished_at "
                "FROM jobs ORDER BY created_at DESC LIMIT 100"
            ),
        }
