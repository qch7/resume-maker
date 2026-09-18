"""经历修订、草稿冲突、建议采用及固定版本组合的事务服务"""

from pathlib import Path, PurePosixPath

from resume_maker.core.errors import Problem, need
from resume_maker.domain.experience import field_value, replace_field, same_experience
from resume_maker.domain.models import Experience, ProjectProfile, ResumeItem
from resume_maker.domain.resume import ResumeDocument
from resume_maker.domain.templates import TEMPLATE_LIBRARY_KEY
from resume_maker.infrastructure.database import Database, dump, now, uid, unpack
from resume_maker.services.history import History
from resume_maker.services.honor_links import resolve_honor_document


class Catalog:
    """经历版本、草稿与组合引用的核心事务服务"""

    def __init__(self, db: Database):
        """保存当前模块所需依赖；供后续业务操作共享使用"""
        self.db = db
        self.history = History(db)

    def project(self, project_id: str) -> dict:
        """读取项目记录且不存在时抛出统一的业务异常"""
        return need(
            self.db.one(
                "SELECT p.*, h.parent_id, b.head_revision FROM projects p "
                "JOIN experience_branches b ON b.project_id=p.id AND b.is_default=1 "
                "LEFT JOIN project_hierarchy h ON h.project_id=p.id WHERE p.id=?",
                (project_id,),
            )
        )

    def revision(self, revision_id: str, project_id: str | None = None) -> dict:
        """读取不可变经历版本并按需验证它属于指定项目"""
        row = need(
            self.db.one(
                "SELECT r.*,b.id AS branch_id,b.name AS branch_name FROM revisions r "
                "JOIN revision_branches rb ON rb.revision_id=r.id "
                "JOIN experience_branches b ON b.id=rb.branch_id WHERE r.id=?",
                (revision_id,),
            )
        )
        if project_id and row["project_id"] != project_id:
            raise Problem("经历版本不属于该项目。", 409)
        return row

    def template(self, template_id: str, include_trashed: bool = False) -> dict:
        """只允许引用具有完整映射的模板；失效引用由用户重新选择或识别"""
        template = need(
            self.db.one(
                "SELECT * FROM templates WHERE id=? AND json_type(mapping_json,'$.plan')='object'",
                (template_id,),
            ),
            "完整简历模板不可用，请重新选择模板或导入 Word 进行 AI 识别。",
        )
        library = self.db.setting(TEMPLATE_LIBRARY_KEY, {"items": {}})
        if not include_trashed and library["items"].get(template_id, {}).get("deleted_at"):
            raise Problem("该模板已移入回收站，请先恢复。", 409)
        return template

    def create_project(self, name: str, roots: list[str]) -> dict:
        """规范化来源并去重登记项目；同时建立初始经历和独立会话"""
        roots = list(dict.fromkeys(str(Path(p).expanduser().resolve(strict=True)) for p in roots))
        if not name.strip() or not roots or any(not Path(p).is_dir() for p in roots):
            raise Problem("请填写项目名称和有效目录。")
        with self.db.transaction() as conn:
            existing = next(
                (
                    row
                    for raw in conn.execute("SELECT * FROM projects WHERE archived=0")
                    if set((row := unpack(raw))["roots"]) == set(roots)
                ),
                None,
            )
            project_id = existing["id"] if existing else self._insert_project(conn, name, roots)
            self._sync_subprojects(conn, project_id)
        return self.project(project_id)

    def _insert_project(self, conn, name: str, roots: list[str]) -> str:
        """在同一事务中登记项目、初始经历及独立会话；来源由调用方验证"""
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
        conn.execute(
            "INSERT INTO conversations(id,project_id,title,created_at,updated_at) "
            "VALUES (?,?,?,?,?)",
            (uid(), project_id, "项目经历梳理", stamp, stamp),
        )
        self.history.initialize(conn, project_id, revision_id, stamp)
        return project_id

    def _sync_subprojects(self, conn, project_id: str) -> None:
        """按已登记来源维护子项目且不读取磁盘；也不改动已有经历和会话"""
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
                # 移除来源只解除分组；旧子项目及其简历引用继续保留
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

    def create_conversation(self, project_id: str, title: str) -> dict:
        """为指定项目创建具有独立历史和输入草稿的会话"""
        self.project(project_id)
        conversation_id, stamp = uid(), now()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO conversations(id,project_id,title,created_at,updated_at) "
                "VALUES (?,?,?,?,?)",
                (conversation_id, project_id, title.strip() or "新会话", stamp, stamp),
            )
        return self.conversation(conversation_id)

    def conversation(self, conversation_id: str) -> dict:
        """读取会话记录且不存在时返回明确的业务错误"""
        return need(self.db.one("SELECT * FROM conversations WHERE id=?", (conversation_id,)))

    def working(self, project_id: str, revision_id: str) -> dict:
        """按覆盖优先级将草稿叠加在固定版本上；返回可编辑工作副本"""
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
                # 新增亮点置顶；其余条目沿用用户排序并移除已删除的亮点
                ids = field_value(content, "order")
                value = [i for i in ids if i not in value] + [i for i in value if i in ids]
            content = replace_field(content, draft["field"], value)
        return content

    def put_draft(self, project_id: str, revision_id: str, field: str, value, version: int):
        """校验字段并按草稿版本写入；拒绝覆盖其他窗口的新修改"""
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
        """原子核对完整草稿集合后撤销且只作用于当前项目与基线且不产生经历版本"""
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
        """校验分支头与草稿版本后发布整个工作副本；原子清理已提交草稿"""
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
                # 无文件引用的 AI 建议没有新证据记录；沿用版本已有引用并允许空值
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
                # 内容改回原值也需通过并发校验；再清理这次确认的全部草稿
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
        """在历史版本所属分支追加恢复版本；保留来源快照及已有版本链"""
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

    def adopt(self, proposal_id: str):
        """检查建议原文与当前内容一致后写入草稿以免覆盖后续人工编辑"""
        proposal = need(self.db.one("SELECT * FROM proposals WHERE id=?", (proposal_id,)))
        conversation = self.conversation(proposal["conversation_id"])
        project_id = conversation["project_id"]
        base_id = proposal["base_revision"]
        branch = self.history.for_revision(project_id, base_id)
        working = self.working(project_id, base_id)
        if proposal["status"] != "pending":
            raise Problem("建议已经处理。", 409)
        if (
            branch["head_revision"] != base_id
            or field_value(working["content"], proposal["target"]) != proposal["before"]
        ):
            raise Problem("建议生成后原文已发生变化，请重新请求或手工合并。", 409)
        replace_field(working["content"], proposal["target"], proposal["after"])
        with self.db.transaction() as conn:
            head = conn.execute(
                "SELECT head_revision FROM experience_branches WHERE id=?", (branch["id"],)
            ).fetchone()[0]
            status = conn.execute(
                "SELECT status FROM proposals WHERE id=?", (proposal_id,)
            ).fetchone()[0]
            actual = conn.execute(
                "SELECT field,version,value_json FROM drafts "
                "WHERE project_id=? AND base_revision=?",
                (project_id, base_id),
            ).fetchall()
            expected = [(d["field"], d["version"], dump(d["value"])) for d in working["drafts"]]
            if (
                head != base_id
                or status != "pending"
                or sorted(tuple(r) for r in actual) != sorted(expected)
            ):
                raise Problem("采用建议时内容发生变化，请刷新后合并。", 409)
            if proposal["target"] == "experience":
                # 建议原文已包含所有草稿；通过并发校验后可由整段建议统一替换
                conn.execute(
                    "DELETE FROM drafts WHERE project_id=? AND base_revision=?",
                    (project_id, base_id),
                )
            row = conn.execute(
                "SELECT version FROM drafts WHERE project_id=? AND base_revision=? AND field=?",
                (project_id, base_id, proposal["target"]),
            ).fetchone()
            conn.execute(
                "INSERT OR REPLACE INTO drafts VALUES (?,?,?,?,?,?,?)",
                (
                    project_id,
                    base_id,
                    proposal["target"],
                    dump(proposal["after"]),
                    row[0] + 1 if row else 1,
                    f"ai:{proposal['snapshot_id'] or ''}",
                    now(),
                ),
            )
            conn.execute("UPDATE proposals SET status='adopted' WHERE id=?", (proposal_id,))
        return self.working(project_id, base_id)

    def save_resume(
        self,
        name: str,
        template_id: str | None,
        items: list[ResumeItem],
        resume_id: str | None = None,
        version: int = 0,
        document: ResumeDocument | None = None,
    ) -> dict:
        """校验项目、版本与亮点归属并以乐观锁保存固定版本组合"""
        seen = set()
        for item in items:
            revision = self.revision(item.revision_id, item.project_id)
            valid = {h["id"] for h in revision["content"]["highlights"]}
            if item.project_id in seen or not set(item.highlight_ids) <= valid:
                raise Problem("组合包含重复项目或无效亮点。")
            if len(item.highlight_ids) != len(set(item.highlight_ids)):
                raise Problem("亮点不能重复。")
            seen.add(item.project_id)
        if template_id:
            self.template(template_id)
        resume_id = resume_id or uid()
        with self.db.transaction() as conn:
            if conn.execute(
                "SELECT 1 FROM resume_deletions WHERE resume_id=?", (resume_id,)
            ).fetchone():
                raise Problem("该简历方案已删除，请切换或新建方案。", 404)
            existing = unpack(
                conn.execute("SELECT * FROM resumes WHERE id=?", (resume_id,)).fetchone()
            )
            if version != (existing["version"] if existing else 0):
                raise Problem("简历组合已在其他窗口修改，请刷新。", 409)
            library = unpack(
                conn.execute(
                    "SELECT value_json FROM settings WHERE key=?", (TEMPLATE_LIBRARY_KEY,)
                ).fetchone()
            )
            deleted = library and library["value"]["items"].get(template_id, {}).get("deleted_at")
            if deleted:
                raise Problem("该模板已移入回收站，请先恢复模板或选择其他模板。", 409)
            if (
                template_id
                and not conn.execute(
                    "SELECT 1 FROM templates WHERE id=?", (template_id,)
                ).fetchone()
            ):
                raise Problem("该模板已永久删除，请选择其他模板。", 409)
            resolved_document = resolve_honor_document(
                self.db, document.model_dump() if document is not None else None, conn
            )
            conn.execute(
                "INSERT OR REPLACE INTO resumes "
                "(id,name,template_id,items_json,version,created_at,updated_at,document_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    resume_id,
                    name.strip() or "我的简历",
                    template_id,
                    dump([i.model_dump() for i in items]),
                    version + 1,
                    existing["created_at"] if existing else now(),
                    now(),
                    dump(resolved_document) if resolved_document is not None else None,
                ),
            )
        return self.db.one("SELECT * FROM resumes WHERE id=?", (resume_id,))

    def delete_resume(self, resume_id: str, version: int) -> None:
        """按版本删除方案；保留项目、模板及历史导出；拒绝覆盖其他窗口的修改"""
        with self.db.transaction() as conn:
            resume = need(
                conn.execute(
                    "SELECT version FROM resumes WHERE id=? AND id NOT IN "
                    "(SELECT resume_id FROM resume_deletions)",
                    (resume_id,),
                ).fetchone(),
                "该简历方案不存在或已删除。",
            )
            if resume["version"] != version:
                raise Problem("简历组合已在其他窗口修改，请先载入服务器组合再删除。", 409)
            conn.execute("INSERT INTO resume_deletions VALUES (?,?)", (resume_id, now()))
