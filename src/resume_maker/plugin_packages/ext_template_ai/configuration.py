"""AI 模板分析的有界修正配置"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings


class Settings(PluginSettings):
    """每轮修正仍经过覆盖和边界校验，失败保留最佳建议"""

    max_analysis_rounds: int = Field(default=3, ge=1, le=8, description="最多模型分析和修正轮数")
