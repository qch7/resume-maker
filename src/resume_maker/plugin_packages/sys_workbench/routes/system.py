"""健康状态、工作台聚合、关闭和备份的 HTTP 入口"""

from typing import Annotated

from fastapi import APIRouter, Depends

from resume_maker.api.dependencies import service
from resume_maker.sdk.services import Workspace

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/state")
def state(
    dep_workspace: Annotated[Workspace, Depends(service("workspace"))],
):
    """聚合项目活动时间、会话、简历、模板及最近任务，供工作台轮询"""
    return dep_workspace.state()
