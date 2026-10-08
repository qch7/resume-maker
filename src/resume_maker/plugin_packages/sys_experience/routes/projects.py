"""项目来源、版本和草稿操作的 HTTP 入口"""

from typing import Annotated

from fastapi import APIRouter, Depends

from resume_maker.api.dependencies import service
from resume_maker.api.schemas import (
    BranchInput,
    DiscardDraftsInput,
    DraftInput,
    ProjectInput,
    ProjectProfileInput,
    SaveInput,
)
from resume_maker.sdk.services import Catalog, Projects

router = APIRouter(prefix="/api", tags=["projects"])


@router.post("/projects/{project_id}/branches")
def create_branch(
    dep_catalog: Annotated[Catalog, Depends(service("catalog"))], project_id: str, body: BranchInput
):
    """从保存版本创建独立经历分支，保留来源和原分支草稿"""
    return dep_catalog.history.create(
        project_id, body.base_revision, body.name, body.include_drafts
    )


@router.post("/projects")
def create_project(
    dep_catalog: Annotated[Catalog, Depends(service("catalog"))], body: ProjectInput
):
    """规范化来源并去重登记项目，同时建立初始经历和独立会话"""
    return dep_catalog.create_project(body.name, body.roots)


@router.get("/projects/{project_id}")
def get_project(
    dep_projects: Annotated[Projects, Depends(service("projects"))],
    project_id: str,
    revision_id: str | None = None,
):
    """读取选定版本的工作副本、历史修订和来源快照供经历编辑器展示"""
    return dep_projects.get_project(project_id, revision_id)


@router.delete("/projects/{project_id}")
def delete_project(
    dep_projects: Annotated[Projects, Depends(service("projects"))], project_id: str
):
    """删除未被简历引用的项目组，返回实际移除范围供工作台清理选中状态"""
    return {"deleted_project_ids": dep_projects.delete(project_id)}


@router.get("/revisions/{revision_id}")
def get_revision(dep_catalog: Annotated[Catalog, Depends(service("catalog"))], revision_id: str):
    """返回指定不可变经历版本，供简历组合恢复其固定引用"""
    return dep_catalog.revision(revision_id)


@router.put("/projects/{project_id}/profile")
def save_profile(
    dep_projects: Annotated[Projects, Depends(service("projects"))],
    project_id: str,
    body: ProjectProfileInput,
):
    """保存用户确认的角色、日期和贡献信息并更新项目活动时间"""
    return dep_projects.save_profile(project_id, body.profile, body.expected_profile)


@router.put("/projects/{project_id}/draft")
def put_draft(
    dep_catalog: Annotated[Catalog, Depends(service("catalog"))], project_id: str, body: DraftInput
):
    """校验字段并按草稿版本写入，拒绝覆盖其他窗口的新修改"""
    return dep_catalog.put_draft(
        project_id, body.base_revision, body.field, body.value, body.version
    )


@router.post("/projects/{project_id}/draft/discard")
def discard_draft(
    dep_catalog: Annotated[Catalog, Depends(service("catalog"))], project_id: str, body: DraftInput
):
    """确认草稿版本仍匹配后删除指定字段的未发布修改"""
    dep_catalog.discard_draft(project_id, body.base_revision, body.field, body.version)
    return dep_catalog.working(project_id, body.base_revision)


@router.post("/projects/{project_id}/drafts/discard")
def discard_drafts(
    dep_catalog: Annotated[Catalog, Depends(service("catalog"))],
    project_id: str,
    body: DiscardDraftsInput,
):
    """一次撤销已确认的整份工作副本，发生并发修改则完整保留草稿"""
    dep_catalog.discard_drafts(project_id, body.base_revision, body.versions)
    return dep_catalog.working(project_id, body.base_revision)


@router.post("/projects/{project_id}/revisions")
def save_revision(
    dep_catalog: Annotated[Catalog, Depends(service("catalog"))], project_id: str, body: SaveInput
):
    """提交整个工作副本，同时校验预期分支头版本"""
    return dep_catalog.save_revision(project_id, body.base_revision, body.expected_head)


@router.post("/projects/{project_id}/restore")
def restore_revision(
    dep_catalog: Annotated[Catalog, Depends(service("catalog"))], project_id: str, body: SaveInput
):
    """根据指定历史经历创建新的恢复版本"""
    return dep_catalog.restore(project_id, body.base_revision, body.expected_head)
