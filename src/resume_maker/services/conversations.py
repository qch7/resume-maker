"""独立会话查询、归档维护和模型上下文重建"""

from resume_maker.core.errors import Problem, need
from resume_maker.domain.experience import field_value, replace_field
from resume_maker.infrastructure.database import dump, now, uid
from resume_maker.infrastructure.observability import record
from resume_maker.services.catalog import Catalog


class Conversations:
    """会话详情、归档状态和模型上下文重建服务"""

    def __init__(self, catalog: Catalog):
        """保存当前模块所需依赖，供后续业务操作共享使用"""
        self.catalog, self.db = catalog, catalog.db

    def archived_conversations(self):
        """按最近更新时间列出归档会话，供设置界面恢复使用"""
        return self.db.all("SELECT * FROM conversations WHERE archived=1 ORDER BY updated_at DESC")

    def get_conversation(self, conversation_id: str):
        """聚合单个会话的消息、建议和任务，保持不同会话上下文隔离"""
        return {
            "conversation": self.conversation(conversation_id),
            "messages": self.db.all(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at",
                (conversation_id,),
            ),
            "proposals": self.db.all(
                "SELECT * FROM proposals WHERE conversation_id=? ORDER BY created_at",
                (conversation_id,),
            ),
            "jobs": self.db.all(
                "SELECT * FROM jobs WHERE conversation_id=? ORDER BY created_at", (conversation_id,)
            ),
        }

    def patch_conversation(self, conversation_id: str, values: dict):
        """更新允许编辑的会话字段且仅在值变化时刷新活动时间"""
        self.conversation(conversation_id)
        values = dict(values)
        if set(values) - {"title", "input_draft", "scope", "archived"}:
            raise Problem("不支持的会话字段。")
        if values:
            with self.db.transaction() as conn:
                current = conn.execute(
                    "SELECT * FROM conversations WHERE id=?", (conversation_id,)
                ).fetchone()
                if any(current[key] != value for key, value in values.items()):
                    values["updated_at"] = now()
                conn.execute(
                    "UPDATE conversations SET "
                    + ",".join(f"{k}=?" for k in values)
                    + " WHERE id=?",
                    (*values.values(), conversation_id),
                )
        return self.conversation(conversation_id)

    def rebuild_conversation(self, conversation_id: str):
        """确认没有活动任务后清除模型会话标识，下轮使用保存的历史重建"""
        self.conversation(conversation_id)
        with self.db.transaction() as conn:
            active = conn.execute(
                "SELECT id FROM jobs WHERE conversation_id=? AND status IN ('running','queued')",
                (conversation_id,),
            ).fetchone()
            if active:
                raise Problem("请先取消或等待当前任务完成。", 409)
            conn.execute(
                "UPDATE conversations SET provider_thread_id=NULL WHERE id=?", (conversation_id,)
            )
            conn.execute(
                "INSERT INTO messages VALUES (?,?,NULL,'system',?,?)",
                (uid(), conversation_id, "下次请求将以当前经历和已保存历史重建模型上下文。", now()),
            )
        record(
            "ai",
            "system",
            "下次请求将以当前经历和已保存历史重建模型上下文。",
            {"role": "system", "text": "下次请求将以当前经历和已保存历史重建模型上下文。"},
            conversation_id=conversation_id,
        )
        return {"ok": True}

    def create_conversation(self, project_id: str, title: str) -> dict:
        """为指定项目创建具有独立历史和输入草稿的会话"""
        self.catalog.project(project_id)
        conversation_id, stamp = uid(), now()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO conversations(id,project_id,title,created_at,updated_at) "
                "VALUES (?,?,?,?,?)",
                (conversation_id, project_id, title.strip() or "新会话", stamp, stamp),
            )
        return self.conversation(conversation_id)

    def conversation(self, conversation_id: str) -> dict:
        """读取会话并在记录缺失时抛出业务异常"""
        return need(self.db.one("SELECT * FROM conversations WHERE id=?", (conversation_id,)))

    def adopt(self, proposal_id: str):
        """检查建议原文和当前内容一致后写入草稿以免覆盖后续人工编辑"""
        proposal = need(self.db.one("SELECT * FROM proposals WHERE id=?", (proposal_id,)))
        conversation = self.conversation(proposal["conversation_id"])
        project_id = conversation["project_id"]
        base_id = proposal["base_revision"]
        branch = self.catalog.history.for_revision(project_id, base_id)
        working = self.catalog.working(project_id, base_id)
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
                # 建议原文已包含所有草稿，通过并发校验后可由整段建议统一替换
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
        return self.catalog.working(project_id, base_id)

    def initialize_project(self, conn, project_id, stamp):
        """在经历建立事务内初始化会话，插件卸载后撤销此贡献"""
        conn.execute(
            "INSERT INTO conversations(id,project_id,title,created_at,updated_at) "
            "VALUES (?,?,?,?,?)",
            (uid(), project_id, "项目经历梳理", stamp, stamp),
        )
