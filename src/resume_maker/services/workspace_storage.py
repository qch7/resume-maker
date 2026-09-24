"""独立保存未提交输入和界面偏好，正式业务版本仍由各服务发布"""

import hashlib
import re

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import dump, now, uid, unpack

PREFIX = "workspace-value:"
PREFERENCES = {
    "rm.theme",
    "rm.layout",
    "rm.sidebarSort",
    "rm.activity",
    "rm.template.library.view",
    "rm.resume.current",
    "rm.template.analysis",
    "rm.template.library",
}


class WorkspaceStorage:
    """提供按键版本校验及删除标记，避免迟到窗口重新写回旧草稿"""

    def __init__(self, db):
        """数据目录和恢复代次共同隔离浏览器恢复副本"""
        self.db = db
        with db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO settings VALUES ('workspace-generation', ?)", (dump(uid()),)
            )
        location = hashlib.sha256(str(db.path.resolve()).encode()).hexdigest()[:16]
        self.namespace = f"{location}:{db.setting('workspace-generation')}"

    def state(self):
        """启动时读取持久草稿，包含删除版本以检查浏览器未完成写入"""
        return {
            "namespace": self.namespace,
            "values": {
                row["key"][len(PREFIX) :]: row["value"]
                for row in self.db.all("SELECT * FROM settings WHERE key LIKE ?", (PREFIX + "%",))
            },
        }

    def save(self, key, value, version):
        """在同一事务内比较版本，重复请求幂等，删除同样推进版本"""
        if not re.fullmatch(r"rm\.[a-zA-Z0-9_.:\-]{1,240}", key):
            raise Problem("草稿标识无效。")
        if value is not None and len(value.encode("utf-8")) > 8_000_000:
            raise Problem("单份草稿超过 8 MB，请缩小照片后重试。", 413)
        with self.db.transaction() as conn:
            row = unpack(
                conn.execute("SELECT * FROM settings WHERE key=?", (PREFIX + key,)).fetchone()
            )
            current = row["value"] if row else {"value": None, "version": 0}
            if current["value"] == value:
                return current
            if current["version"] != version and key not in PREFERENCES:
                raise Problem("此草稿已在其他窗口修改，本页输入已保留，请选择要保留的内容。", 409)
            saved = {"value": value, "version": current["version"] + 1, "updated_at": now()}
            conn.execute(
                "INSERT OR REPLACE INTO settings VALUES (?,?)", (PREFIX + key, dump(saved))
            )
        return saved
