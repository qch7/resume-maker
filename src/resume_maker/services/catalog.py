"""经历修订、草稿冲突、建议采用及固定版本组合的事务服务。"""

from pathlib import Path

from resume_maker.core.errors import Problem, need
from resume_maker.domain.experience import field_value, replace_field
from resume_maker.domain.models import Experience, ProjectProfile, ResumeItem
from resume_maker.infrastructure.database import Database, dump, now, uid, unpack


class Catalog:
    """经历版本、草稿与组合引用的核心事务服务。"""

    def __init__(self, db: Database):
        """保存当前模块所需依赖，供后续业务操作共享使用。"""
        self.db = db

    def project(self, project_id: str) -> dict:
        """读取项目记录，不存在时抛出统一的业务异常。"""
        return need(self.db.one("SELECT * FROM projects WHERE id=?", (project_id,)))

    def revision(self, revision_id: str, project_id: str | None = None) -> dict:
        """读取不可变经历版本，并按需验证它属于指定项目。"""
        row = need(self.db.one("SELECT * FROM revisions WHERE id=?", (revision_id,)))
        if project_id and row["project_id"] != project_id:
            raise Problem("经历版本不属于该项目。", 409)
        return row

    def create_project(self, name: str, roots: list[str]) -> dict:
        """规范化来源并去重登记项目，同时建立初始经历和独立会话。"""
        roots = list(dict.fromkeys(str(Path(p).expanduser().resolve(strict=True)) for p in roots))
        if not name.strip() or not roots or any(not Path(p).is_dir() for p in roots):
            raise Problem("请填写项目名称和有效目录。")
        for project in self.db.all("SELECT * FROM projects WHERE archived=0"):
            if set(project["roots"]) == set(roots):
                return project
        project_id, revision_id, stamp = uid(), uid(), now()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO projects VALUES (?,?,?,?,?,0,?,?)",
                (
                    project_id,
                    name.strip(),
                    dump(roots),
                    dump(ProjectProfile().model_dump()),
                    revision_id,
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
        self.create_conversation(project_id, "项目经历梳理")
        return self.project(project_id)

    def create_conversation(self, project_id: str, title: str) -> dict:
        """为指定项目创建具有独立历史和输入草稿的会话。"""
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
        """读取会话记录，不存在时返回明确的业务错误。"""
        return need(self.db.one("SELECT * FROM conversations WHERE id=?", (conversation_id,)))

    def working(self, project_id: str, revision_id: str) -> dict:
        """按覆盖优先级将草稿叠加在固定版本上，返回可编辑工作副本。"""
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
        """依次应用草稿，并协调增删亮点后的旧排序草稿。"""
        for draft in drafts:
            value = draft["value"]
            if draft["field"] == "order":
                # 将旧排序与草稿中新增、删除的亮点重新协调。
                ids = field_value(content, "order")
                value = [i for i in value if i in ids] + [i for i in ids if i not in value]
            content = replace_field(content, draft["field"], value)
        return content

    def put_draft(self, project_id: str, revision_id: str, field: str, value, version: int):
        """校验字段并按草稿版本写入；拒绝覆盖其他窗口的新修改。"""
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
        """确认草稿版本仍匹配后删除指定字段的未发布修改。"""
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

    def save_field(self, project_id: str, revision_id: str, field: str, expected_head: str) -> dict:
        """发布所选字段为不可变新版本，并把其他未保存内容保留为草稿。"""
        base = self.revision(revision_id, project_id)
        working = self.working(project_id, revision_id)
        effective = working["content"]
        value = field_value(effective, field)
        if field == "order":
            ids = field_value(base["content"], "order")
            value = [i for i in value if i in ids] + [i for i in ids if i not in value]
        content = replace_field(base["content"], field, value)
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
                snapshot_id = draft["origin"][3:]
        new_id = uid()
        with self.db.transaction() as conn:
            head = conn.execute(
                "SELECT head_revision FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            if head[0] != expected_head:
                raise Problem("项目已有新版本，请刷新后再保存；草稿仍然保留。", 409)
            actual = conn.execute(
                "SELECT field,version,value_json FROM drafts "
                "WHERE project_id=? AND base_revision=?",
                (project_id, revision_id),
            ).fetchall()
            expected = [(d["field"], d["version"], dump(d["value"])) for d in working["drafts"]]
            if sorted(tuple(row) for row in actual) != sorted(expected):
                raise Problem("保存时草稿发生变化，请重试。", 409)
            if content == base["content"]:
                # 回到原内容也要确认草稿，但仍须检查并发，且不能移除相互覆盖的有效编辑。
                if effective == base["content"]:
                    conn.execute(
                        "DELETE FROM drafts WHERE project_id=? AND base_revision=?",
                        (project_id, revision_id),
                    )
                else:
                    remaining = [d for d in working["drafts"] if d["field"] != field]
                    if self._apply_drafts(base["content"], remaining) == effective:
                        conn.execute(
                            "DELETE FROM drafts WHERE project_id=? AND base_revision=? AND field=?",
                            (project_id, revision_id, field),
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
                    f"保存 {field}",
                    stamp,
                ),
            )
            conn.execute(
                "UPDATE projects SET head_revision=?,updated_at=? WHERE id=?",
                (new_id, stamp, project_id),
            )
            conn.execute(
                "DELETE FROM drafts WHERE project_id=? AND base_revision=?",
                (project_id, revision_id),
            )
            # 其他字段的未发布修改迁移到新版本草稿，不能随本次单项保存一起发布。
            if field != "experience":
                pending = self._difference(content, effective)
                for key, value in pending:
                    conn.execute(
                        "INSERT INTO drafts VALUES (?,?,?,?,1,?,?)",
                        (
                            project_id,
                            new_id,
                            key,
                            dump(value),
                            f"ai:{snapshot_id}" if origin == "ai" else "manual",
                            stamp,
                        ),
                    )
        return self.revision(new_id)

    @staticmethod
    def _difference(base: dict, effective: dict) -> list[tuple]:
        """拆分两个经历副本的字段差异，用于迁移未发布草稿。"""
        result = []
        if field_value(base, "meta") != field_value(effective, "meta"):
            result.append(("meta", field_value(effective, "meta")))
        old = {h["id"]: h for h in base["highlights"]}
        new = {h["id"]: h for h in effective["highlights"]}
        for point_id in old.keys() | new.keys():
            if old.get(point_id) != new.get(point_id):
                result.append((f"highlight:{point_id}", new.get(point_id)))
        if field_value(base, "order") != field_value(effective, "order"):
            result.append(("order", field_value(effective, "order")))
        return result

    def restore(self, project_id: str, revision_id: str, expected_head: str) -> dict:
        """以历史内容创建新版本，同时保留原快照来源及现有版本链。"""
        source = self.revision(revision_id, project_id)
        new_id, stamp = uid(), now()
        with self.db.transaction() as conn:
            head = conn.execute(
                "SELECT head_revision FROM projects WHERE id=?", (project_id,)
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
            conn.execute(
                "UPDATE projects SET head_revision=?,updated_at=? WHERE id=?",
                (new_id, stamp, project_id),
            )
        return self.revision(new_id)

    def adopt(self, proposal_id: str):
        """检查建议原文与当前内容一致后写入草稿，避免覆盖后续人工编辑。"""
        proposal = need(self.db.one("SELECT * FROM proposals WHERE id=?", (proposal_id,)))
        conversation = self.conversation(proposal["conversation_id"])
        project_id = conversation["project_id"]
        base_id = proposal["base_revision"]
        working = self.working(project_id, base_id)
        if proposal["status"] != "pending":
            raise Problem("建议已经处理。", 409)
        if (
            self.project(project_id)["head_revision"] != base_id
            or field_value(working["content"], proposal["target"]) != proposal["before"]
        ):
            raise Problem("建议生成后原文已发生变化，请重新请求或手工合并。", 409)
        replace_field(working["content"], proposal["target"], proposal["after"])
        with self.db.transaction() as conn:
            head = conn.execute(
                "SELECT head_revision FROM projects WHERE id=?", (project_id,)
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
                # 建议原文已包含所有草稿，通过并发校验后可由整段建议统一替换。
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
                    f"ai:{proposal['snapshot_id']}",
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
    ) -> dict:
        """校验项目、版本与亮点归属，并以乐观锁保存固定版本组合。"""
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
            need(self.db.one("SELECT id FROM templates WHERE id=?", (template_id,)), "模板不存在")
        resume_id = resume_id or uid()
        with self.db.transaction() as conn:
            existing = unpack(
                conn.execute("SELECT * FROM resumes WHERE id=?", (resume_id,)).fetchone()
            )
            if version != (existing["version"] if existing else 0):
                raise Problem("简历组合已在其他窗口修改，请刷新。", 409)
            conn.execute(
                "INSERT OR REPLACE INTO resumes VALUES (?,?,?,?,?,?,?)",
                (
                    resume_id,
                    name.strip() or "我的简历",
                    template_id,
                    dump([i.model_dump() for i in items]),
                    version + 1,
                    existing["created_at"] if existing else now(),
                    now(),
                ),
            )
        return self.db.one("SELECT * FROM resumes WHERE id=?", (resume_id,))
