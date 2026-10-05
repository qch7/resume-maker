"""项目来源、版本和草稿操作的 HTTP 入口"""

from typing import Annotated

from fastapi import APIRouter, Depends

from resume_maker.api.dependencies import service
from resume_maker.api.schemas import (
    RevealSourceInput,
)
from resume_maker.sdk.services import Projects

router = APIRouter(prefix="/api", tags=["projects"])


@router.post("/projects/{project_id}/sources/reveal")
def reveal_source(
    dep_projects: Annotated[Projects, Depends(service("projects"))],
    project_id: str,
    body: RevealSourceInput,
):
    """验证来源文件属于项目快照后，在本机文件管理器中定位"""
    from resume_maker.integrations.desktop import reveal_file

    reveal_file(dep_projects.source_path(project_id, body.snapshot_id, body.source, body.path))
    return {"ok": True}
