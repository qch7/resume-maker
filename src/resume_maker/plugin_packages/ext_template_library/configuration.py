"""模板回收站和定期清理的运行配置"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings


class Settings(PluginSettings):
    """有效保留天数同步展示到界面，清理仍需校验模板引用"""

    trash_retention_days: int = Field(default=30, ge=1, le=3650, description="回收站保留天数")
    trash_sweep_seconds: float = Field(default=60, ge=10, le=86400, description="清理检查间隔秒数")
