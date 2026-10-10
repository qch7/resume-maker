"""活动日志的有界保留和短连接策略"""

import json
from pathlib import Path

from pydantic import Field, field_validator

from resume_maker.domain.activity import normalize_hidden_rules
from resume_maker.sdk.configuration import PluginSettings

MAX_DETAIL_CHARS = 262_144
MAX_DETAIL_DEPTH = 16
MAX_DETAIL_ITEMS = 1000
HISTORY_BATCH_SIZE = 200
RULE_DEFAULTS = json.loads(
    Path(__file__).with_name("activity_rules.json").read_text(encoding="utf-8")
)
DEFAULT_HIDDEN_RULES = normalize_hidden_rules("\n".join(RULE_DEFAULTS["hidden_rules"])).splitlines()


class ActivityPolicy(PluginSettings):
    """重建日志服务时按有效配置执行保留，采集偏好继续持久保存"""

    max_records: int = Field(default=50_000, ge=100, le=1_000_000, description="最多保留日志条数")
    retention_days: int = Field(default=30, ge=1, le=3650, description="日志保留天数")
    lock_timeout_seconds: float = Field(default=2, ge=0.1, le=10, description="日志库锁等待秒数")
    hidden_rules: list[str] = Field(
        default=DEFAULT_HIDDEN_RULES, max_length=100, description="日志界面默认隐藏规则，每项一条"
    )

    @field_validator("hidden_rules")
    @classmethod
    def validate_hidden_rules(cls, value):
        """文件和界面查询共用规则校验，空列表明确关闭默认过滤"""
        return normalize_hidden_rules("\n".join(value)).splitlines()
