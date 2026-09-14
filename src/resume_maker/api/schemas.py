"""HTTP 请求模型；领域模型单独维护，避免业务层依赖 FastAPI。"""

from typing import Any

from pydantic import Field

from resume_maker.domain.models import Model, ResumeItem
from resume_maker.domain.resume import ResumeDocument
from resume_maker.domain.templates import TemplatePlan


class ProjectInput(Model):
    """项目登记或来源重绑请求，限制名称和来源数量。"""

    name: str = Field(min_length=1, max_length=200)
    roots: list[str] = Field(min_length=1, max_length=30)


class DraftInput(Model):
    """带基础修订和草稿版本号的字段编辑请求。"""

    base_revision: str
    field: str
    value: Any = None
    version: int = Field(default=0, ge=0)


class SaveInput(Model):
    """发布或恢复经历的请求，携带所属分支预期头版本防止并发覆盖。"""

    base_revision: str
    expected_head: str


class BranchInput(Model):
    """从指定版本创建命名分支，可独立复制其未发布草稿。"""

    name: str = Field(min_length=1, max_length=80)
    base_revision: str
    include_drafts: bool = True


class MessageInput(Model):
    """绑定经历版本、讨论范围与幂等标识的会话请求。"""

    text: str = Field(min_length=1, max_length=30000)
    kind: str = "chat"
    base_revision: str
    scope: str = "all"
    request_key: str = Field(min_length=1, max_length=100)


class ConversationInput(Model):
    """会话可修改字段的白名单，空值表示不修改该字段。"""

    title: str | None = Field(default=None, max_length=200)
    input_draft: str | None = Field(default=None, max_length=30000)
    scope: str | None = None
    archived: bool | None = None


class ResumeInput(Model):
    """包含模板、固定版本条目及乐观锁版本的简历请求。"""

    name: str = Field(min_length=1, max_length=200)
    template_id: str | None = None
    items: list[ResumeItem]
    version: int = 0
    document: ResumeDocument | None = None


class TemplateInput(Model):
    """本机模板路径及半开区间形式的经历替换范围。"""

    path: str
    name: str = ""
    start: int
    end: int


class PathInput(Model):
    """需要由后端校验并读取的本机路径。"""

    path: str


class TemplateAnalysisInput(Model):
    """分析本机模板，同时提供当前栏目的名称供语义匹配，不发送个人字段值。"""

    path: str
    document: ResumeDocument


class TemplateMappingInput(Model):
    """用户核对或修改后的声明式映射。"""

    plan: TemplatePlan


class AdaptiveTemplateInput(TemplateMappingInput):
    """将分析快照及核对后的映射登记为可复用模板。"""

    name: str = Field(min_length=1, max_length=200)
    document: ResumeDocument
    items: list[ResumeItem]


class TemplatePreviewInput(TemplateMappingInput):
    """用当前资料及固定项目引用试填，预览不会保存简历组合。"""

    document: ResumeDocument
    items: list[ResumeItem]


class RevealSourceInput(Model):
    """用项目快照和来源相对路径定位文件，不接受任意本机绝对路径。"""

    snapshot_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    path: str = Field(min_length=1)
