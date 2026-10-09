"""任务执行器的并发和停止策略"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings


class TaskPolicy(PluginSettings):
    """配置变更排空现有执行器后才创建新的线程池"""

    max_workers: int = Field(default=4, ge=1, le=32, description="任务执行线程数")
    max_pending_tasks: int = Field(default=256, ge=1, le=4096, description="未结束任务及排队总数")
    close_timeout_seconds: float = Field(default=30, ge=1, le=300, description="任务关闭等待秒数")
    owner_close_timeout_seconds: float = Field(
        default=30, ge=1, le=300, description="单个任务所有者的关闭等待秒数"
    )
