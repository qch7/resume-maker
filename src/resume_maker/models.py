from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(Model):
    source: str = ""
    path: str = ""
    line_start: int = Field(default=0, ge=0)
    line_end: int = Field(default=0, ge=0)
    quote: str = ""
    status: Literal["code", "document", "user", "unverified"] = "unverified"


class Highlight(Model):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(max_length=200)
    text: str = Field(max_length=10000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=30)


class Experience(Model):
    title: str = Field(max_length=200)
    period: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=300)
    stack: list[str] = Field(default_factory=list, max_length=60)
    description: str = Field(default="", max_length=10000)
    highlights: list[Highlight] = Field(default_factory=list, max_length=60)


class ProjectProfile(Model):
    role: str = ""
    period: str = ""
    contribution: str = ""
    outcomes: str = ""
    notes: str = ""


class ProviderSettings(Model):
    executable: str = "codex"
    model: str = ""
    profile: str = ""
    timeout_seconds: int = Field(default=1200, ge=30, le=7200)


class SuggestedChange(Model):
    target: str
    title: str
    text: str
    reason: str
    evidence: list[Evidence]


class AIResult(Model):
    reply: str
    experience: Experience | None
    changes: list[SuggestedChange]
    questions: list[str]


class ResumeItem(Model):
    project_id: str
    revision_id: str
    highlight_ids: list[str]
