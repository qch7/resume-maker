"""简历临时预览的排队、总截止和失败合并配置"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings


class Settings(PluginSettings):
    """重建服务后使用新预算，已有渲染仍先实际排空"""

    max_preview_requests: int = Field(default=16, ge=1, le=128, description="预览执行及等待总数")
    preview_timeout_seconds: float = Field(
        default=660, ge=5, le=3600, description="预览排队及全部生成阶段的总秒数"
    )
    failed_preview_retry_seconds: float = Field(
        default=2, ge=0, le=30, description="相同输入预览失败的自动重试间隔"
    )
