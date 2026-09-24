"""本机隐私规则、脱敏预览和发送记录管理"""

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import Database, dump
from resume_maker.integrations.privacy_store import PrivacyStore


class Privacy:
    """保存隐私设置并复用模型出口使用的本机脱敏引擎"""

    def __init__(self, db: Database, store: PrivacyStore):
        """绑定当前实例的持久设置和隐私出口"""
        self.db, self.store = db, store

    def get(self):
        """返回强制隐私策略和用户可补充的敏感词"""
        saved = {
            row["key"]: row["value"]
            for row in self.db.all(
                "SELECT key,value_json FROM settings "
                "WHERE key IN ('privacy_terms','privacy_terms_version')"
            )
        }
        return {
            "enabled": True,
            "transport": "codex-cli-sandbox",
            "isolation": "read-only-material-tools",
            "images": "local-ocr",
            "ocr": {
                "engine": "RapidOCR / PP-OCRv4 mobile",
                "device": "CPU",
                "threads": 2,
                "base_side": 960,
                "retry_side": 2000,
            },
            "terms": saved.get("privacy_terms", []),
            "version": saved.get("privacy_terms_version", 0),
        }

    def save_terms(self, terms: list[str], expected_version: int):
        """同一事务内保存规范化敏感词和版本，冲突时保留原有设置"""
        terms = list(dict.fromkeys(value.strip() for value in terms if value.strip()))
        if any(len(value) > 500 for value in terms):
            raise Problem("单条敏感词最多 500 个字符。")
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT value_json FROM settings WHERE key='privacy_terms_version'"
            ).fetchone()
            version = int(row[0]) if row else 0
            if version != expected_version:
                raise Problem("敏感词已在其他窗口修改，请重新打开设置后再保存。", 409)
            conn.executemany(
                "INSERT OR REPLACE INTO settings VALUES (?,?)",
                [("privacy_terms", dump(terms)), ("privacy_terms_version", dump(version + 1))],
            )
        return {"terms": terms, "version": version + 1}

    def preview(self, text: str):
        """只在内存中预览脱敏结果，不保存原文和还原表"""
        redactor = self.store.redactor()
        return {"text": redactor.prompt(text), "replacements": redactor.count}

    def requests(self):
        """读取已脱敏的发送记录，不包含响应原文和真实值映射"""
        return self.db.setting("privacy_audit", [])

    def clear_requests(self):
        """清除当前实例的发送记录，保留敏感词及简历资料"""
        self.db.set_setting("privacy_audit", [])
        return {"cleared": True}
