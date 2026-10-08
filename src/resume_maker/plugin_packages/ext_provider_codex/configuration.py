"""本机 CLI 版本探测配置，模型连接继续使用持久化设置"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings


class Settings(PluginSettings):
    """版本检查超时独立于实际模型请求超时"""

    inspection_timeout_seconds: float = Field(
        default=15, ge=1, le=120, description="CLI 版本探测秒数"
    )
