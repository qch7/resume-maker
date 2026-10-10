"""启动监督器的运维等待参数"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SupervisorPolicy(BaseModel):
    """就绪等待和候选观察分别计时，正常服务没有寿命上限"""

    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True, allow_inf_nan=False
    )

    startup_timeout_seconds: float = Field(
        default=120, ge=10, le=600, description="宿主就绪等待秒数"
    )
    health_observation_seconds: float = Field(
        default=3, ge=1, le=60, description="候选持续健康秒数"
    )
    health_poll_seconds: float = Field(
        default=0.5, ge=0.1, le=5, description="候选健康检查间隔秒数"
    )

    @field_validator(
        "startup_timeout_seconds",
        "health_observation_seconds",
        "health_poll_seconds",
        mode="before",
    )
    @classmethod
    def numeric_duration(cls, value):
        """等待时间拒绝布尔值，允许环境中的十进制秒数"""
        if isinstance(value, bool):
            raise ValueError("等待时间须为秒数")
        return value
