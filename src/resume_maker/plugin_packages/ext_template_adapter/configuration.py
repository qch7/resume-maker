"""模板适配任务关闭配置"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings


class Settings(PluginSettings):
    """关闭等待超时继续保留任务依赖和原件"""

    close_timeout_seconds: float = Field(
        default=8, ge=1, le=300, description="模板任务关闭等待秒数"
    )
