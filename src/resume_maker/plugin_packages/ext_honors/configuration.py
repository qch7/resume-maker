"""荣誉任务的关闭配置"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings


class Settings(PluginSettings):
    """等待证书识别和取消真正结束后释放资源"""

    close_timeout_seconds: float = Field(
        default=10, ge=1, le=300, description="荣誉任务关闭等待秒数"
    )
