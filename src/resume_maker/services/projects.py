"""项目详情查询、本人贡献信息与来源目录维护。"""

from pathlib import Path

from resume_maker.core.errors import Problem
from resume_maker.domain.models import ProjectProfile
from resume_maker.infrastructure.database import dump, now
from resume_maker.services.catalog import Catalog


class Projects:
    """项目详情查询、本人贡献资料和来源路径维护。"""

    def __init__(self, catalog: Catalog):
        """保存当前模块所需依赖，供后续业务操作共享使用。"""
        self.catalog, self.db = catalog, catalog.db

    def get_project(self, project_id: str, revision_id: str | None = None):
        """读取选定版本的工作副本、历史修订与来源快照供经历编辑器展示。"""
        project = self.catalog.project(project_id)
        selected = revision_id or project["head_revision"]
        return {
            "project": project,
            "working": self.catalog.working(project_id, selected),
            "revision_snapshot": self.db.one(
                "SELECT * FROM snapshots WHERE id=?",
                (self.catalog.revision(selected, project_id)["snapshot_id"],),
            ),
            "revisions": self.db.all(
                "SELECT * FROM revisions WHERE project_id=? ORDER BY number DESC", (project_id,)
            ),
            "snapshots": self.db.all(
                "SELECT * FROM snapshots WHERE project_id=? ORDER BY created_at DESC LIMIT 10",
                (project_id,),
            ),
        }

    def save_profile(self, project_id: str, profile: ProjectProfile):
        """保存用户确认的角色、日期与贡献信息，并更新项目活动时间。"""
        self.catalog.project(project_id)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE projects SET profile_json=?,updated_at=? WHERE id=?",
                (dump(profile.model_dump()), now(), project_id),
            )
        return self.catalog.project(project_id)

    def update_sources(self, project_id: str, name: str, sources: list[str]):
        """校验并重新绑定项目来源目录，保留已经生成的经历与历史。"""
        self.catalog.project(project_id)
        roots = [str(Path(p).expanduser().resolve(strict=True)) for p in sources]
        if any(not Path(p).is_dir() for p in roots):
            raise Problem("来源必须是目录。")
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE projects SET name=?,roots_json=?,updated_at=? WHERE id=?",
                (name, dump(list(dict.fromkeys(roots))), now(), project_id),
            )
        return self.catalog.project(project_id)
