"""本机来源检查的只读进程等待策略"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings


class SourcePolicy(PluginSettings):
    """Git 等待独立于材料读取权限和敏感文件过滤"""

    git_timeout_seconds: float = Field(
        default=20, ge=1, le=120, description="只读 Git 查询等待秒数"
    )
