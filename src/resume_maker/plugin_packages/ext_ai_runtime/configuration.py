"""统一模型出口的实际并发及等待预算"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings


class Settings(PluginSettings):
    """设置重建提供方实例，已有任务在旧配置下实际排空"""

    max_parallel_calls: int = Field(default=4, ge=1, le=32, description="模型实际调用并发数")
    max_waiting_calls: int = Field(default=32, ge=1, le=256, description="模型等待调用数")
    wait_timeout_seconds: float = Field(default=1200, ge=1, le=7200, description="模型排队等待秒数")
