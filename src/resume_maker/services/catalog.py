"""经历修订和草稿冲突的独立事务服务"""

from pathlib import Path, PurePosixPath

from resume_maker.core.errors import Problem, need
from resume_maker.domain.experience import field_value, replace_field, same_experience
from resume_maker.domain.models import Experience, ProjectProfile
from resume_maker.sdk.observation import internal
from resume_maker.sdk.records import dump, now, uid, unpack
from resume_maker.sdk.storage import RelationalStore
from resume_maker.services.history import History


class Catalog:
    """经历版本和草稿的核心事务服务"""

    def __init__(self, db: RelationalStore, *, assets):
        """保存当前模块所需依赖，供后续业务操作共享使用"""
        self.db, self.assets = db, assets
        self.history = History(db)
        self.project_initializers = {}

    @internal
    def workspace_state(self, conn):
        """在调用方快照内返回本模块拥有的工作台资料"""
        result = {
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
                for row in conn.execute("SELECT * FROM experience_branches ORDER BY created_at,id")
            ],
        }
        return result

    def publish_evidence(self, project_id, identifier, fingerprint, manifest, files):
        """经历插件在同一事务发布来源快照和不可变原件引用"""
        staged = self.assets.stage_bundle("sys.experience", files)
        with self.db.transaction() as conn:
            need(
                conn.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone(),
                "项目已删除，证据未发布。",
            )
            self.assets.publish_bundle(conn, "sys.experience", f"snapshots/{identifier}", staged)
            conn.execute(
                "INSERT INTO snapshots VALUES (?,?,?,?,?)",
                (identifier, project_id, fingerprint, dump(manifest), now()),
            )
        return self.db.one("SELECT * FROM snapshots WHERE id=?", (identifier,))

    @internal
    def on_project_created(self, owner, initialize):
        """登记同事务的项目初始化回调并返回作用域撤销函数"""
        if owner in self.project_initializers:
            raise Problem("项目初始化贡献重复。", 409)
        self.project_initializers[owner] = initialize

        def detach():
            """排空请求后移除当前所有者的初始化回调"""
            if self.project_initializers.get(owner) is initialize:
                del self.project_initializers[owner]

        return detach

    def project(self, project_id: str) -> dict:
        """读取项目并在记录缺失时抛出业务异常"""
        return need(
            self.db.one(
                "SELECT p.*, h.parent_id, b.head_revision FROM projects p "
                "JOIN experience_branches b ON b.project_id=p.id AND b.is_default=1 "
                "LEFT JOIN project_hierarchy h ON h.project_id=p.id WHERE p.id=?",
                (project_id,),
            )
        )

    def revision(self, revision_id: str, project_id: str | None = None, conn=None) -> dict:
        """读取不可变经历版本并按需验证它属于指定项目"""
        if conn is None:
            with self.db.connect() as connection:
                return self._revision(connection, revision_id, project_id)
        return self._revision(conn, revision_id, project_id)

    def _revision(self, conn, revision_id, project_id):
        """在已有会话读取不可变修订，不重新进入公共事务入口"""
        row = need(
            unpack(
                conn.execute(
                    "SELECT r.*,b.id AS branch_id,b.name AS branch_name FROM revisions r "
                    "JOIN revision_branches rb ON rb.revision_id=r.id "
                    "JOIN experience_branches b ON b.id=rb.branch_id WHERE r.id=?",
                    (revision_id,),
                ).fetchone()
            ),
            "经历版本已不存在或其项目已删除。",
        )
        if project_id and row["project_id"] != project_id:
            raise Problem("经历版本不属于该项目。", 409)
        return row

    def branch(self, project_id, revision_id):
        """公开读取修订所属分支，不暴露历史管理对象"""
        return self.history.for_revision(project_id, revision_id)

    def apply_suggestion(self, conn, project_id, revision_id, field, before, after, snapshot_id):
        """在调用方写事务中核对当前分支和原文，再原子更新经历草稿"""
        revision = self.revision(revision_id, project_id, conn)
        head = conn.execute(
            "SELECT head_revision FROM experience_branches WHERE id=?", (revision["branch_id"],)
        ).fetchone()[0]
        drafts = [
            unpack(row)
            for row in conn.execute(
                "SELECT * FROM drafts WHERE project_id=? AND base_revision=? "
                "ORDER BY CASE field WHEN 'experience' THEN 0 WHEN 'order' THEN 2 ELSE 1 END, "
                "updated_at",
                (project_id, revision_id),
            )
        ]
        content = self._apply_drafts(revision["content"], drafts)
        if head != revision_id or field_value(content, field) != before:
            raise Problem("建议生成后原文已发生变化，请重新请求或手工合并。", 409)
        replace_field(content, field, after)
        if field == "experience":
            conn.execute(
                "DELETE FROM drafts WHERE project_id=? AND base_revision=?",
                (project_id, revision_id),
            )
        row = conn.execute(
            "SELECT version FROM drafts WHERE project_id=? AND base_revision=? AND field=?",
            (project_id, revision_id, field),
        ).fetchone()
        conn.execute(
            "INSERT OR REPLACE INTO drafts VALUES (?,?,?,?,?,?,?)",
            (
                project_id,
                revision_id,
                field,
                dump(after),
                row[0] + 1 if row else 1,
                f"ai:{snapshot_id or ''}",
                now(),
            ),
        )

    def create_project(self, name: str, roots: list[str]) -> dict:
        """规范化来源并去重登记项目，同时建立初始经历和已注册的扩展资料"""
        roots = list(dict.fromkeys(str(Path(p).expanduser().resolve(strict=True)) for p in roots))
        if not name.strip() or any(not Path(p).is_dir() for p in roots):
            raise Problem("请填写项目名称和有效目录。")
        with self.db.transaction() as conn:
            existing = next(
                (
                    row
                    for raw in conn.execute("SELECT * FROM projects WHERE archived=0")
                    if roots and set((row := unpack(raw))["roots"]) == set(roots)
                ),
                None,
            )
            project_id = existing["id"] if existing else self._insert_project(conn, name, roots)
            self._sync_subprojects(conn, project_id)
        return self.project(project_id)

    def _insert_project(self, conn, name: str, roots: list[str]) -> str:
        """在同一事务中登记项目、初始经历及扩展资料，来源由调用方验证"""
        project_id, revision_id, stamp = uid(), uid(), now()
        conn.execute(
            "INSERT INTO projects VALUES (?,?,?,?,0,?,?)",
            (
                project_id,
                name.strip(),
                dump(roots),
                dump(ProjectProfile().model_dump()),
                stamp,
                stamp,
            ),
        )
        conn.execute(
            "INSERT INTO revisions VALUES (?,?,NULL,NULL,1,?,?,?,?)",
            (
                revision_id,
                project_id,
                dump(Experience(title=name).model_dump()),
                "manual",
                "初始版本",
                stamp,
            ),
        )
        for initialize in tuple(self.project_initializers.values()):
            initialize(conn, project_id, stamp)
        self.history.initialize(conn, project_id, revision_id, stamp)
        return project_id

    def _sync_subprojects(self, conn, project_id: str) -> None:
        """根据已登记来源维护子项目"""
        parent = need(
            unpack(conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
        )
        roots = parent["roots"] if len(parent["roots"]) > 1 else []
        children = [
            unpack(row)
            for row in conn.execute(
                "SELECT p.* FROM projects p JOIN project_hierarchy h ON h.project_id=p.id "
                "WHERE h.parent_id=?",
                (project_id,),
            )
        ]
        retained = {}
        for child in children:
            if len(child["roots"]) == 1 and child["roots"][0] in roots and not child["archived"]:
                retained[child["roots"][0]] = child["id"]
            else:
                # 移除来源只解除分组，旧子项目及其简历引用继续保留
                conn.execute("DELETE FROM project_hierarchy WHERE project_id=?", (child["id"],))
        for root in roots:
            if root in retained:
                continue
            candidate = next(
                (
                    row
                    for raw in conn.execute(
                        "SELECT p.* FROM projects p "
                        "LEFT JOIN project_hierarchy h ON h.project_id=p.id "
                        "WHERE p.archived=0 AND h.parent_id IS NULL AND p.id<>?",
                        (project_id,),
                    )
                    if (row := unpack(raw))["roots"] == [root]
                ),
                None,
            )
            child_id = (
                candidate["id"]
                if candidate
                else self._insert_project(
                    conn, PurePosixPath(root.replace("\\", "/")).name or parent["name"], [root]
                )
            )
            conn.execute("INSERT INTO project_hierarchy VALUES (?,?)", (child_id, project_id))

    def sync_subprojects(self, project_id: str) -> None:
        """来源变更后幂等更新整体项目的子项目关联"""
        with self.db.transaction() as conn:
            self._sync_subprojects(conn, project_id)

    def working(self, project_id: str, revision_id: str) -> dict:
        """按覆盖优先级将草稿叠加在固定版本上，返回可编辑工作副本"""
        content = self.revision(revision_id, project_id)["content"]
        drafts = self.db.all(
            "SELECT * FROM drafts WHERE project_id=? AND base_revision=? "
            "ORDER BY CASE field WHEN 'experience' THEN 0 WHEN 'order' THEN 2 ELSE 1 END, "
            "updated_at",
            (project_id, revision_id),
        )
        return {"content": self._apply_drafts(content, drafts), "drafts": drafts}

    @staticmethod
    def _apply_drafts(content: dict, drafts: list[dict]) -> dict:
        """依次应用草稿并协调增删亮点后的旧排序草稿"""
        for draft in drafts:
            value = draft["value"]
            if draft["field"] == "order":
                # 新增亮点置顶，其余条目沿用用户排序并移除已删除的亮点
                ids = field_value(content, "order")
                value = [i for i in ids if i not in value] + [i for i in value if i in ids]
            content = replace_field(content, draft["field"], value)
        return content

    def put_draft(self, project_id: str, revision_id: str, field: str, value, version: int):
        """校验字段并按草稿版本写入，拒绝覆盖其他窗口的新修改"""
        content = self.working(project_id, revision_id)["content"]
        replace_field(content, field, value)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT version FROM drafts WHERE project_id=? AND base_revision=? AND field=?",
                (project_id, revision_id, field),
            ).fetchone()
            if version != (row[0] if row else 0):
                raise Problem("草稿已在其他窗口修改，请刷新后合并。", 409)
            conn.execute(
                "INSERT OR REPLACE INTO drafts VALUES (?,?,?,?,?,'manual',?)",
                (project_id, revision_id, field, dump(value), version + 1, now()),
            )
        return self.working(project_id, revision_id)

    def discard_draft(self, project_id: str, revision_id: str, field: str, version: int):
        """确认草稿版本仍匹配后删除指定字段的未发布修改"""
        self.revision(revision_id, project_id)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT version FROM drafts WHERE project_id=? AND base_revision=? AND field=?",
                (project_id, revision_id, field),
            ).fetchone()
            if version != (row[0] if row else 0):
                raise Problem("草稿已在其他窗口修改，请刷新后合并。", 409)
            conn.execute(
                "DELETE FROM drafts WHERE project_id=? AND base_revision=? AND field=?",
                (project_id, revision_id, field),
            )

    def discard_drafts(self, project_id: str, revision_id: str, versions: dict[str, int]):
        """在同一事务中核对并撤销当前项目和基线的完整草稿集合"""
        self.revision(revision_id, project_id)
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT field,version FROM drafts WHERE project_id=? AND base_revision=?",
                (project_id, revision_id),
            ).fetchall()
            if dict(rows) != versions:
                raise Problem("草稿已在其他窗口修改，请取消后重新确认；改动尚未撤销。", 409)
            conn.execute(
                "DELETE FROM drafts WHERE project_id=? AND base_revision=?",
                (project_id, revision_id),
            )

    def save_revision(self, project_id: str, revision_id: str, expected_head: str) -> dict:
        """校验分支头和草稿版本后发布整个工作副本，原子清理已提交草稿"""
        base = self.revision(revision_id, project_id)
        branch = self.history.for_revision(project_id, revision_id)
        working = self.working(project_id, revision_id)
        content = working["content"]
        if not content["title"].strip() or any(
            not h["title"].strip() or not h["text"].strip() for h in content["highlights"]
        ):
            raise Problem("保存版本前请填写项目标题和各条亮点的标题、正文；草稿已保留。")
        ids = [h["id"] for h in content["highlights"]]
        if len(ids) != len(set(ids)):
            raise Problem("亮点 ID 不能重复。")
        origin = "ai" if any(d["origin"].startswith("ai:") for d in working["drafts"]) else "manual"
        snapshot_id = base["snapshot_id"]
        for draft in working["drafts"]:
            if draft["origin"].startswith("ai:"):
                # 无文件引用的 AI 建议没有新证据记录，沿用版本已有引用并允许空值
                snapshot_id = draft["origin"][3:] or snapshot_id
        new_id = uid()
        with self.db.transaction() as conn:
            head = conn.execute(
                "SELECT head_revision FROM experience_branches WHERE id=?", (branch["id"],)
            ).fetchone()
            if head[0] != expected_head:
                raise Problem("项目已有新版本，请刷新后再保存；草稿仍然保留。", 409)
            if revision_id != head[0]:
                raise Problem("这是分支的历史版本，请先从此版本创建分支，或恢复为新版本。", 409)
            actual = conn.execute(
                "SELECT field,version,value_json FROM drafts "
                "WHERE project_id=? AND base_revision=?",
                (project_id, revision_id),
            ).fetchall()
            expected = [(d["field"], d["version"], dump(d["value"])) for d in working["drafts"]]
            if sorted(tuple(row) for row in actual) != sorted(expected):
                raise Problem("保存时草稿发生变化，请重试。", 409)
            if same_experience(content, base["content"]):
                # 内容改回原值也需通过并发校验，再清理这次确认的全部草稿
                conn.execute(
                    "DELETE FROM drafts WHERE project_id=? AND base_revision=?",
                    (project_id, revision_id),
                )
                return base
            number = conn.execute(
                "SELECT MAX(number)+1 FROM revisions WHERE project_id=?", (project_id,)
            ).fetchone()[0]
            stamp = now()
            conn.execute(
                "INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    new_id,
                    project_id,
                    revision_id,
                    snapshot_id,
                    number,
                    dump(content),
                    origin,
                    "保存经历",
                    stamp,
                ),
            )
            self.history.advance(conn, branch, new_id, stamp)
            conn.execute(
                "DELETE FROM drafts WHERE project_id=? AND base_revision=?",
                (project_id, revision_id),
            )
        return self.revision(new_id)

    def restore(self, project_id: str, revision_id: str, expected_head: str) -> dict:
        """在历史版本所属分支追加恢复版本，保留来源快照及已有版本链"""
        source = self.revision(revision_id, project_id)
        branch = self.history.for_revision(project_id, revision_id)
        new_id, stamp = uid(), now()
        with self.db.transaction() as conn:
            head = conn.execute(
                "SELECT head_revision FROM experience_branches WHERE id=?", (branch["id"],)
            ).fetchone()[0]
            if head != expected_head:
                raise Problem("项目已有新版本，请刷新后再恢复。", 409)
            if conn.execute(
                "SELECT 1 FROM drafts WHERE project_id=? AND base_revision=?", (project_id, head)
            ).fetchone():
                raise Problem("当前有未保存草稿，请先保存或取消后恢复历史版本。", 409)
            number = conn.execute(
                "SELECT MAX(number)+1 FROM revisions WHERE project_id=?", (project_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    new_id,
                    project_id,
                    head,
                    source["snapshot_id"],
                    number,
                    dump(source["content"]),
                    "restore",
                    f"恢复 r{source['number']}",
                    stamp,
                ),
            )
            self.history.advance(conn, branch, new_id, stamp)
        return self.revision(new_id)
