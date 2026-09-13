"""项目详情查询、本人贡献信息与来源目录维护。"""

from pathlib import Path, PurePosixPath, PureWindowsPath

from resume_maker.core.errors import Problem, need
from resume_maker.domain.models import ProjectProfile
from resume_maker.infrastructure.database import dump, now
from resume_maker.integrations.desktop import reveal_file
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
            "branch": self.catalog.history.for_revision(project_id, selected),
            "branches": self.catalog.history.branches(project_id),
            "working": self.catalog.working(project_id, selected),
            "uncommitted": self.uncommitted(project_id),
            "revision_snapshot": self.db.one(
                "SELECT * FROM snapshots WHERE id=?",
                (self.catalog.revision(selected, project_id)["snapshot_id"],),
            ),
            "revisions": self.db.all(
                "SELECT r.*,b.id AS branch_id,b.name AS branch_name FROM revisions r "
                "JOIN revision_branches rb ON rb.revision_id=r.id "
                "JOIN experience_branches b ON b.id=rb.branch_id "
                "WHERE r.project_id=? ORDER BY r.number DESC",
                (project_id,),
            ),
            "snapshots": self.db.all(
                "SELECT * FROM snapshots WHERE project_id=? ORDER BY created_at DESC LIMIT 10",
                (project_id,),
            ),
        }

    def uncommitted(self, project_id: str) -> list[dict]:
        """列出各版本上实际不同的工作副本，仅供历史树展示，不创建修订。"""
        result = []
        for row in self.db.all(
            "SELECT base_revision,MAX(updated_at) AS updated_at FROM drafts "
            "WHERE project_id=? GROUP BY base_revision",
            (project_id,),
        ):
            base = self.catalog.revision(row["base_revision"], project_id)
            content = self.catalog.working(project_id, base["id"])["content"]
            if content != base["content"]:
                result.append({**row, "content": content})
        return result

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
        project = self.catalog.project(project_id)
        roots = list(dict.fromkeys(str(Path(p).expanduser().resolve(strict=True)) for p in sources))
        if any(not Path(p).is_dir() for p in roots):
            raise Problem("来源必须是目录。")
        with self.db.transaction() as conn:
            if project["parent_id"]:
                if len(roots) != 1:
                    raise Problem("子项目只能关联一个来源目录，多个来源请在整体项目中配置。")
                parent = need(
                    self.db.one("SELECT * FROM projects WHERE id=?", (project["parent_id"],))
                )
                original = project["roots"][0]
                if roots[0] != original and roots[0] in parent["roots"]:
                    raise Problem("该目录已属于同组的其他子项目。")
                parent_roots = [roots[0] if root == original else root for root in parent["roots"]]
                conn.execute(
                    "UPDATE projects SET roots_json=?,updated_at=? WHERE id=?",
                    (
                        dump(parent_roots),
                        now(),
                        project["parent_id"],
                    ),
                )
            conn.execute(
                "UPDATE projects SET name=?,roots_json=?,updated_at=? WHERE id=?",
                (name, dump(list(dict.fromkeys(roots))), now(), project_id),
            )
            self.catalog._sync_subprojects(conn, project["parent_id"] or project_id)
        return self.catalog.project(project_id)

    def reveal_source(self, project_id: str, snapshot_id: str, source: str, path: str) -> None:
        """按历史快照解析来源，拒绝越界路径和已移走的文件，避免打开错误仓库。"""
        self.catalog.project(project_id)
        snapshot = need(
            self.db.one(
                "SELECT * FROM snapshots WHERE id=? AND project_id=?", (snapshot_id, project_id)
            ),
            "找不到此项目的来源快照。",
        )
        relative = PurePosixPath(path.replace("\\", "/"))
        if (
            relative.is_absolute()
            or PureWindowsPath(path).drive
            or ".." in relative.parts
            or ":" in path
        ):
            raise Problem("来源文件路径必须位于项目目录内。")
        manifest = snapshot["manifest"]
        root_info = next((s for s in manifest["sources"] if s["id"] == source), None)
        if root_info is None or not any(
            f["source"] == source and f["path"] == path for f in manifest["files"]
        ):
            raise Problem("该文件不在来源快照中。", 404)
        try:
            root = Path(root_info["path"]).resolve(strict=True)
            target = (root / relative).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise Problem("来源文件已移动或不存在，请检查项目来源路径。", 404) from exc
        # 快照创建后文件可能被替换为符号链接，再次解析并验证实际目标。
        if not target.is_relative_to(root):
            raise Problem("来源文件路径必须位于项目目录内。")
        if not target.is_file():
            raise Problem("来源路径不是文件。", 404)
        reveal_file(target)
