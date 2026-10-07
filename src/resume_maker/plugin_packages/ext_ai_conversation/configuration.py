"""经历 AI 队列和进度流的等待配置"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings


class Settings(PluginSettings):
    """独立调用和宿主调度均使用同一份队列策略"""

    close_timeout_seconds: float = Field(
        default=8, ge=1, le=300, description="经历任务关闭等待秒数"
    )
    queue_poll_seconds: float = Field(
        default=0.5, ge=0.1, le=10, description="独立队列检查间隔秒数"
    )
    event_poll_seconds: float = Field(default=0.5, ge=0.1, le=10, description="进度流检查间隔秒数")
