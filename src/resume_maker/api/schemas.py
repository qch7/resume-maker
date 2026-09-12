"""HTTP 请求模型；领域模型单独维护，避免业务层依赖 FastAPI。"""

from typing import Any

from pydantic import Field

from resume_maker.domain.models import Model, ResumeItem


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
    """发布或恢复经历的请求，携带预期项目头防止并发覆盖。"""

    base_revision: str
    field: str
    expected_head: str


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


class TemplateInput(Model):
    """本机模板路径及半开区间形式的经历替换范围。"""

    path: str
    name: str = ""
    start: int
    end: int


class PathInput(Model):
    """需要由后端校验并读取的本机路径。"""

    path: str
