"""健康状态、工作台聚合、关闭和备份的 HTTP 入口"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from resume_maker.api.dependencies import service
from resume_maker.sdk.services import Workspace

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/state")
def state(
    dep_workspace: Annotated[Workspace, Depends(service("workspace"))],
    request: Request,
):
    """聚合项目活动时间、会话、简历、模板及最近任务，供工作台轮询"""
    body, etag = dep_workspace.poll(request.headers.get("if-none-match"))
    return Response(
        body,
        status_code=304 if body is None else 200,
        media_type="application/json",
        headers={"ETag": etag},
    )
