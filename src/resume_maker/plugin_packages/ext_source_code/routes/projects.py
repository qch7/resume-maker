"""项目来源、版本和草稿操作的 HTTP 入口"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from resume_maker.api.dependencies import service
from resume_maker.api.schemas import (
    PathInput,
    ProjectSourcesInput,
)
from resume_maker.sdk.services import Projects, SourceAccess

router = APIRouter(prefix="/api", tags=["projects"])


@router.post("/projects/scan")
def scan(body: PathInput, dep_sources: Annotated[SourceAccess, Depends(service("sources"))]):
    """将用户选择的路径交给来源扫描器，返回待确认的项目分组"""
    return dep_sources.scan(Path(body.path))


@router.put("/projects/{project_id}/sources")
def update_sources(
    dep_projects: Annotated[Projects, Depends(service("projects"))],
    project_id: str,
    body: ProjectSourcesInput,
):
    """校验并重新绑定项目来源目录，保留已经生成的经历和历史"""
    return dep_projects.update_sources(
        project_id, body.name, body.roots, body.expected_name, body.expected_roots
    )
