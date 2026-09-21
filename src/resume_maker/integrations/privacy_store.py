"""从本机资料构造敏感词集合并保存有界的脱敏发送记录"""

import json

from resume_maker.infrastructure.database import dump, now, uid
from resume_maker.integrations.privacy import Redactor


class PrivacyStore:
    """原始资料和敏感词保留在本机数据库，外发记录不保存还原表"""

    def __init__(self, db=None):
        """允许独立脚本只使用格式规则，应用实例额外加载本机已知资料"""
        self.db = db

    def redactor(self):
        """每轮重新读取保存资料和自定义词，避免多用户实例共享敏感值"""
        redactor = Redactor(self.db.setting("privacy_terms", []) if self.db else [])
        if self.db:
            for row in self.db.all("SELECT document_json FROM resumes"):
                redactor.learn(row["document"])
            for row in self.db.all("SELECT value_json FROM settings WHERE key LIKE 'honor:%'"):
                redactor.learn(row["value"])
        return redactor

    def record(self, payload, count):
        """原子保存最多十条已脱敏请求，单次请求内容和数量都有上限"""
        identifier = uid()
        if self.db:
            entry = {
                "id": identifier,
                "created_at": now(),
                "replacements": count,
                "status": "prepared",
                "payload": payload,
            }
            with self.db.transaction() as conn:
                row = conn.execute(
                    "SELECT value_json FROM settings WHERE key='privacy_audit'"
                ).fetchone()
                history = json.loads(row[0]) if row else []
                conn.execute(
                    "INSERT OR REPLACE INTO settings VALUES (?,?)",
                    ("privacy_audit", dump([entry, *history][:10])),
                )
        return identifier

    def finish(self, identifier, status):
        """仅记录发送状态，不保存异常正文或模型响应中的真实资料"""
        if self.db:
            with self.db.transaction() as conn:
                row = conn.execute(
                    "SELECT value_json FROM settings WHERE key='privacy_audit'"
                ).fetchone()
                history = json.loads(row[0]) if row else []
                for entry in history:
                    if entry["id"] == identifier:
                        entry["status"] = status
                conn.execute(
                    "INSERT OR REPLACE INTO settings VALUES (?,?)", ("privacy_audit", dump(history))
                )
