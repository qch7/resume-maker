"""经历、来源证据、AI 建议与固定版本简历的数据契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    """拒绝未知字段的基础模型，约束客户端与 AI 输入。"""

    model_config = ConfigDict(extra="forbid")


class Evidence(Model):
    """来源文件、行号和引文组成的证据及其核验状态。"""

    source: str = ""
    path: str = ""
    line_start: int = Field(default=0, ge=0)
    line_end: int = Field(default=0, ge=0)
    quote: str = ""
    status: Literal["code", "document", "user", "unverified"] = "unverified"


class Highlight(Model):
    """具有稳定标识的经历亮点，包含标题、正文与证据。"""

    id: str = Field(min_length=1, max_length=100)
    title: str = Field(max_length=200)
    text: str = Field(max_length=10000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=30)


class Experience(Model):
    """可发布的完整项目经历数据，修订后保持不可变。"""

    title: str = Field(max_length=200)
    period: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=300)
    stack: list[str] = Field(default_factory=list, max_length=60)
    description: str = Field(default="", max_length=10000)
    highlights: list[Highlight] = Field(default_factory=list, max_length=60)


class ProjectProfile(Model):
    """由用户本人补充和确认的角色、日期、贡献及成果。"""

    role: str = ""
    period: str = ""
    contribution: str = ""
    outcomes: str = ""
    notes: str = ""


ReasoningEffort = Literal["", "minimal", "low", "medium", "high", "xhigh"]
AIFunction = Literal[
    "project_analysis",
    "conversation",
    "highlight_edit",
    "template_analysis",
    "template_repair",
    "connection_check",
]


class AISettings(Model):
    """模型和思考强度覆盖；空值表示继承上一级配置。"""

    model: str = ""
    reasoning_effort: ReasoningEffort = ""

    @field_validator("model")
    @classmethod
    def trim_model(cls, value: str) -> str:
        """清除模型名称首尾空格，使纯空白输入按继承配置处理。"""
        return value.strip()


class ProviderSettings(AISettings):
    """CLI 连接、全局默认值和各 AI 功能的可保存配置。"""

    executable: str = "codex"
    profile: str = ""
    timeout_seconds: int = Field(default=1200, ge=30, le=7200)
    functions: dict[AIFunction, AISettings] = Field(default_factory=dict)

    def for_function(self, function: AIFunction) -> "ProviderSettings":
        """逐字段合并功能覆盖与全局默认，返回独立的本次任务配置快照。"""
        override = self.functions.get(function, AISettings())
        return self.model_copy(
            update={
                "model": override.model or self.model,
                "reasoning_effort": override.reasoning_effort or self.reasoning_effort,
                "functions": {},
            }
        )


class SuggestedChange(Model):
    """针对既有亮点的结构化修改建议，等待人工采用。"""

    target: str
    title: str
    text: str
    reason: str
    evidence: list[Evidence]


class AIResult(Model):
    """Provider 返回的回复、完整经历、局部建议及待确认问题。"""

    reply: str
    experience: Experience | None
    changes: list[SuggestedChange]
    questions: list[str]


class ResumeItem(Model):
    """简历对特定项目版本及其亮点的固定引用。"""

    project_id: str
    revision_id: str
    highlight_ids: list[str]
