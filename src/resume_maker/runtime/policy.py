"""插件管理的下载、候选和计划等待策略"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings

PACKAGE_DOWNLOAD_MAX_BYTES = 512 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 128 * 1024
WINDOW_LEASE_SECONDS = 10


class PluginPolicy(PluginSettings):
    """计划保留原有确认屏障，等待超时不会替代用户确认"""

    download_timeout_seconds: float = Field(default=5, ge=1, le=60, description="下载网络等待秒数")
    download_close_timeout_seconds: float = Field(
        default=10, ge=1, le=120, description="下载取消后的关闭等待秒数"
    )
    install_timeout_seconds: float = Field(default=300, ge=30, le=1800, description="离线安装秒数")
    candidate_timeout_seconds: float = Field(default=120, ge=10, le=600, description="候选验收秒数")
    plan_lifetime_seconds: float = Field(
        default=600, ge=60, le=3600, description="变更计划有效秒数"
    )
