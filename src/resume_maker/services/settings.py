"""工作台设置、默认栏目并发保存和模型连接检查"""

import threading
from pathlib import Path

from resume_maker.core.errors import Problem
from resume_maker.domain.models import ProviderSettings
from resume_maker.domain.resume_defaults import ResumeDefaults
from resume_maker.infrastructure.database import Database, dump, uid, unpack
from resume_maker.integrations.providers.base import Provider
from resume_maker.integrations.providers.cli import inspect_cli


class Settings:
    """管理实例设置，模型调用使用应用入口注入的统一 Provider"""

    def __init__(self, db: Database, data_dir: Path, provider: Provider):
        """保存本机配置存储和模型出口，不依赖后台任务队列"""
        self.db, self.data_dir, self.provider = db, data_dir, provider

    def get(self):
        """返回完整 Provider 配置和当前数据目录"""
        return {"provider": self._provider_settings().model_dump(), "data_dir": str(self.data_dir)}

    def _provider_settings(self):
        """从持久设置读取当前模型参数并补齐默认值"""
        return ProviderSettings.model_validate(self.db.setting("provider", {}))

    def save_provider(self, settings: ProviderSettings):
        """保存已校验的模型参数，后续任务读取新的配置"""
        self.db.set_setting("provider", settings.model_dump())
        return settings

    def resume_defaults(self):
        """读取默认栏目，尚未设置时由前端提供初始配置"""
        return self.db.setting("resume_defaults")

    def save_resume_defaults(self, defaults: ResumeDefaults):
        """在同一事务内校验版本和保存默认栏目，防止多窗口覆盖"""
        with self.db.transaction() as conn:
            row = unpack(
                conn.execute(
                    "SELECT value_json FROM settings WHERE key='resume_defaults'"
                ).fetchone()
            )
            version = row["value"]["version"] if row else 0
            if defaults.version != version:
                raise Problem("默认栏目已在其他窗口修改，请重新打开设置后再试。", 409)
            saved = defaults.model_copy(update={"version": version + 1})
            conn.execute(
                "INSERT OR REPLACE INTO settings VALUES (?,?)",
                ("resume_defaults", dump(saved.model_dump())),
            )
        return saved

    def inspect_provider(self):
        """只检查本机 Codex CLI 的版本，不触发模型请求"""
        return inspect_cli(self._provider_settings())

    def check_provider(self):
        """通过统一隐私出口验证独立连接配置，保留真实结构化响应"""
        result = self.provider.run(
            workspace=self.data_dir / "workspaces" / f"check-{uid()}",
            prompt="连接测试。不要使用工具或读取文件。reply 写连接成功；"
            "experience=null，changes=[]，questions=[]。",
            thread_id=None,
            settings=self._provider_settings().for_function("connection_check"),
            cancelled=threading.Event(),
            emit=lambda *_: None,
        )
        return {"ok": True, "reply": result.reply}
