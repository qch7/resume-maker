"""活动日志的有界保留和短连接策略"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings

MAX_DETAIL_CHARS = 262_144
MAX_DETAIL_DEPTH = 16
MAX_DETAIL_ITEMS = 1000
HISTORY_BATCH_SIZE = 200


class ActivityPolicy(PluginSettings):
    """重建日志服务时按有效配置执行保留，采集偏好继续持久保存"""

    max_records: int = Field(default=50_000, ge=100, le=1_000_000, description="最多保留日志条数")
    retention_days: int = Field(default=30, ge=1, le=3650, description="日志保留天数")
    lock_timeout_seconds: float = Field(default=2, ge=0.1, le=10, description="日志库锁等待秒数")
