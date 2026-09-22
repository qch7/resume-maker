"""受本机认证保护的日志分页、详情、快照导出和删除"""

import re
from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime, BaseModel, Field, field_validator

from resume_maker.api.dependencies import ServicesDep
from resume_maker.core.errors import need
from resume_maker.infrastructure.activity import DEFAULT_POLLING_PATHS

router = APIRouter(prefix="/api/activity", tags=["activity"])


class ClientActivity(BaseModel):
    """浏览器只提交有界文字，禁止注入服务器级别或关联标识"""

    event: str = Field(max_length=80)
    message: str = Field(max_length=2000)
    stack: str = Field(default="", max_length=12000)
    path: str = Field(default="", max_length=2000)


@router.post("/client")
def client_activity(body: ClientActivity, services: ServicesDep):
    """持久化浏览器异常和失败请求，写入本身不产生递归 HTTP 日志"""
    services.db.activity.write(
        "client", body.event, body.message, body.model_dump(), source="browser", level="error"
    )
    return {"ok": True}


class ActivityQuery(BaseModel):
    """日志列表和导出共用筛选条件"""

    category: str = Field(default="", max_length=200)
    level: str = Field(default="", max_length=80)
    q: str = Field(default="", max_length=500)
    trace_id: str = Field(default="", max_length=100)
    job_id: str = Field(default="", max_length=100)
    conversation_id: str = Field(default="", max_length=100)
    since: str = Field(default="", max_length=40)
    until: str = Field(default="", max_length=40)
    hide_polling: bool = False
    hide_maintenance: bool = False
    polling_paths: str = Field(default=DEFAULT_POLLING_PATHS, max_length=2000)
    hidden_rules: str | None = Field(default=None, max_length=4000)
    after: int | None = Field(default=None, ge=0)
    before: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=1, le=500)

    @field_validator("hidden_rules")
    @classmethod
    def validate_hidden_rules(cls, value):
        """限制统一规则的数量和语法，避免无界查询或误填查询参数"""
        if value is None:
            return value
        lines = list(dict.fromkeys(line.strip() for line in value.splitlines() if line.strip()))
        if len(lines) > 100:
            raise ValueError("最多填写 100 条隐藏规则")
        for line in lines:
            if not re.fullmatch(
                r"(?:(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) )?/api/[^\s?#]*|"
                r"(?:ai|task|system|client):[A-Za-z0-9_.*-]+|"
                r"[A-Za-z_*][A-Za-z0-9_.*-]*\.[A-Za-z0-9_.*-]+",
                line,
            ):
                raise ValueError("隐藏规则须为 API 路径、操作名或类型:事件，支持方法前缀和星号")
        return "\n".join(lines)


@router.get("")
def list_activity(services: ServicesDep, query: Annotated[ActivityQuery, Query()]):
    """按时间游标返回事件摘要和当前筛选计数"""
    return services.db.activity.page(**query.model_dump())


@router.get("/export")
def export_activity(services: ServicesDep, query: Annotated[ActivityQuery, Query()]):
    """导出匹配筛选的脱敏 JSONL 快照，响应不包含实例令牌"""
    return StreamingResponse(
        services.db.activity.export(**query.model_dump()),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="system-activity.jsonl"'},
    )


@router.get("/{identifier}")
def activity_detail(identifier: int, services: ServicesDep):
    """按需展开单条活动，已过期记录返回明确错误"""
    return need(services.db.activity.detail(identifier), "日志已过期或不存在。")


class ActivityDeletion(BaseModel):
    """明确传入带时区的删除截止时间，空值表示删除全部日志"""

    before: AwareDatetime | None


@router.delete("")
def delete_activity(body: ActivityDeletion, services: ServicesDep):
    """只删除独立日志库中的记录，保留业务资料和历史补录标记"""
    before = body.before.astimezone(UTC).isoformat() if body.before is not None else None
    return {"deleted": services.db.activity.delete(before=before)}
