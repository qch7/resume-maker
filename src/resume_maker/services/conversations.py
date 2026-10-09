"""独立会话查询、归档维护和模型上下文重建"""

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import now, uid
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
            "conversation": self.catalog.conversation(conversation_id),
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
        self.catalog.conversation(conversation_id)
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
        return self.catalog.conversation(conversation_id)

    def rebuild_conversation(self, conversation_id: str):
        """确认没有活动任务后清除模型会话标识，下轮使用保存的历史重建"""
        self.catalog.conversation(conversation_id)
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
