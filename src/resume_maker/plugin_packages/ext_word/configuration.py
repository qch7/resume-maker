"""Word 排版和受控进程关闭配置"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings


class Settings(PluginSettings):
    """渲染和旧文档转换采用相同等待策略，配置切换保留进程排空屏障"""

    render_timeout_seconds: float = Field(default=90, ge=5, le=600, description="Word 执行秒数")
    close_timeout_seconds: float = Field(default=30, ge=1, le=300, description="Word 关闭等待秒数")
    preview_scale: float = Field(default=1.3, ge=0.5, le=3, description="PNG 分页预览栅格倍率")
