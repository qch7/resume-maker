"""业务 SQLite 的锁等待策略"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings


class DatabasePolicy(PluginSettings):
    """锁等待不改变事务、资料版本和 WAL 规则"""

    lock_timeout_seconds: float = Field(default=10, ge=0.1, le=60, description="SQLite 锁等待秒数")
