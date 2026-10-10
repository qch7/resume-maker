"""受本机认证保护的日志分页、详情、快照导出和删除"""

from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from resume_maker.api.dependencies import service
from resume_maker.core.errors import need
from resume_maker.domain.activity import (
    ActivityCaptureSettings,
    ActivityRuleDefaults,
    normalize_hidden_rules,
)
from resume_maker.infrastructure.database import Database
from resume_maker.plugin_packages.sys_activity.services.activity import (
    capture_settings,
    save_capture_settings,
)

router = APIRouter(prefix="/api/activity", tags=["activity"])


class ClientActivity(BaseModel):
    """浏览器只提交有界文字，禁止注入服务器级别或关联标识"""

    event: str = Field(max_length=80)
    message: str = Field(max_length=2000)
    stack: str = Field(default="", max_length=12000)
    path: str = Field(default="", max_length=2000)


class ActivityQuery(BaseModel):
    """日志列表和导出共用筛选条件"""

    model_config = ConfigDict(extra="forbid")
    category: str = Field(default="", max_length=200)
    level: str = Field(default="", max_length=80)
    q: str = Field(default="", max_length=500)
    trace_id: str = Field(default="", max_length=100)
    job_id: str = Field(default="", max_length=100)
    conversation_id: str = Field(default="", max_length=100)
    since: str = Field(default="", max_length=40)
    until: str = Field(default="", max_length=40)
    hide_polling: bool = False
    show_starts: bool = True
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
        return normalize_hidden_rules(value)


class ActivityDeletion(BaseModel):
    """明确传入带时区的删除截止时间，空值表示删除全部日志"""

    before: AwareDatetime | None


@router.post("/client")
def client_activity(body: ClientActivity, dep_db: Annotated[Database, Depends(service("db"))]):
    """持久化浏览器异常和失败请求，写入本身不产生递归 HTTP 日志"""
    dep_db.activity.write(
        "client", body.event, body.message, body.model_dump(), source="browser", level="error"
    )
    return {"ok": True}


@router.get("")
def list_activity(
    dep_db: Annotated[Database, Depends(service("db"))], query: Annotated[ActivityQuery, Query()]
):
    """按时间游标返回事件摘要和当前筛选计数"""
    return dep_db.activity.page(**query.model_dump())


@router.get("/export")
def export_activity(
    dep_db: Annotated[Database, Depends(service("db"))], query: Annotated[ActivityQuery, Query()]
):
    """导出匹配筛选的脱敏 JSONL 快照，响应不包含实例令牌"""
    return StreamingResponse(
        dep_db.activity.export(**query.model_dump()),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="system-activity.jsonl"'},
    )


@router.get("/settings")
def activity_settings(dep_db: Annotated[Database, Depends(service("db"))]):
    """读取后端实际采集类别，不受页面隐藏规则影响"""
    return capture_settings(dep_db.activity)


@router.get("/defaults")
def activity_defaults(dep_db: Annotated[Database, Depends(service("db"))]) -> ActivityRuleDefaults:
    """发布文件配置生效后的默认规则，界面无需重新构建"""
    return ActivityRuleDefaults(hidden_rules=dep_db.activity.policy.hidden_rules)


@router.put("/settings")
def update_activity_settings(
    body: ActivityCaptureSettings, dep_db: Annotated[Database, Depends(service("db"))]
):
    """保存采集类别并立即用于后续日志写入"""
    return save_capture_settings(dep_db.activity, body)


@router.get("/{identifier}")
def activity_detail(identifier: int, dep_db: Annotated[Database, Depends(service("db"))]):
    """按需展开单条活动，已过期记录返回明确错误"""
    return need(dep_db.activity.detail(identifier), "日志已过期或不存在。")


@router.delete("")
def delete_activity(body: ActivityDeletion, dep_db: Annotated[Database, Depends(service("db"))]):
    """只删除独立日志库中的记录，保留业务资料和历史补录标记"""
    before = body.before.astimezone(UTC).isoformat() if body.before is not None else None
    return {"deleted": dep_db.activity.delete(before=before)}
