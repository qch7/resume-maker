"""项目来源、版本和草稿操作的 HTTP 入口"""

from pathlib import Path

from fastapi import APIRouter

from resume_maker.api.dependencies import ServicesDep
from resume_maker.api.schemas import (
    BranchInput,
    DiscardDraftsInput,
    DraftInput,
    PathInput,
    ProjectInput,
    RevealSourceInput,
    SaveInput,
)
from resume_maker.domain.models import ProjectProfile
from resume_maker.integrations.sources import scan_collection

router = APIRouter(prefix="/api", tags=["projects"])


@router.post("/projects/{project_id}/branches")
def create_branch(services: ServicesDep, project_id: str, body: BranchInput):
    """从保存版本创建独立经历分支，保留来源和原分支草稿"""
    return services.catalog.history.create(
        project_id, body.base_revision, body.name, body.include_drafts
    )


@router.post("/projects/scan")
def scan(services: ServicesDep, body: PathInput):
    """将用户选择的路径交给来源扫描器，返回待确认的项目分组"""
    return scan_collection(Path(body.path))


@router.post("/projects")
def create_project(services: ServicesDep, body: ProjectInput):
    """规范化来源并去重登记项目，同时建立初始经历和独立会话"""
    return services.catalog.create_project(body.name, body.roots)


@router.get("/projects/{project_id}")
def get_project(services: ServicesDep, project_id: str, revision_id: str | None = None):
    """读取选定版本的工作副本、历史修订和来源快照供经历编辑器展示"""
    return services.projects.get_project(project_id, revision_id)


@router.delete("/projects/{project_id}")
def delete_project(services: ServicesDep, project_id: str):
    """删除未被简历引用的项目组，返回实际移除范围供工作台清理选中状态"""
    return {"deleted_project_ids": services.projects.delete(project_id)}


@router.get("/revisions/{revision_id}")
def get_revision(services: ServicesDep, revision_id: str):
    """返回指定不可变经历版本，供简历组合恢复其固定引用"""
    return services.catalog.revision(revision_id)


@router.put("/projects/{project_id}/profile")
def save_profile(services: ServicesDep, project_id: str, body: ProjectProfile):
    """保存用户确认的角色、日期和贡献信息并更新项目活动时间"""
    return services.projects.save_profile(project_id, body)


@router.put("/projects/{project_id}/sources")
def update_sources(services: ServicesDep, project_id: str, body: ProjectInput):
    """校验并重新绑定项目来源目录，保留已经生成的经历和历史"""
    return services.projects.update_sources(project_id, body.name, body.roots)


@router.post("/projects/{project_id}/sources/reveal")
def reveal_source(services: ServicesDep, project_id: str, body: RevealSourceInput):
    """验证来源文件属于项目快照后，在本机文件管理器中定位"""
    services.projects.reveal_source(project_id, body.snapshot_id, body.source, body.path)
    return {"ok": True}


@router.put("/projects/{project_id}/draft")
def put_draft(services: ServicesDep, project_id: str, body: DraftInput):
    """校验字段并按草稿版本写入，拒绝覆盖其他窗口的新修改"""
    return services.catalog.put_draft(
        project_id, body.base_revision, body.field, body.value, body.version
    )


@router.post("/projects/{project_id}/draft/discard")
def discard_draft(services: ServicesDep, project_id: str, body: DraftInput):
    """确认草稿版本仍匹配后删除指定字段的未发布修改"""
    services.catalog.discard_draft(project_id, body.base_revision, body.field, body.version)
    return services.catalog.working(project_id, body.base_revision)


@router.post("/projects/{project_id}/drafts/discard")
def discard_drafts(services: ServicesDep, project_id: str, body: DiscardDraftsInput):
    """一次撤销已确认的整份工作副本，发生并发修改则完整保留草稿"""
    services.catalog.discard_drafts(project_id, body.base_revision, body.versions)
    return services.catalog.working(project_id, body.base_revision)


@router.post("/projects/{project_id}/revisions")
def save_revision(services: ServicesDep, project_id: str, body: SaveInput):
    """提交整个工作副本，同时校验预期分支头版本"""
    return services.catalog.save_revision(project_id, body.base_revision, body.expected_head)


@router.post("/projects/{project_id}/restore")
def restore_revision(services: ServicesDep, project_id: str, body: SaveInput):
    """根据指定历史经历创建新的恢复版本"""
    return services.catalog.restore(project_id, body.base_revision, body.expected_head)
