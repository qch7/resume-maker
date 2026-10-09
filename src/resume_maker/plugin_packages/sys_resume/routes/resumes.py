"""固定版本简历组合和导出下载的 HTTP 入口"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from resume_maker.api.dependencies import service
from resume_maker.api.schemas import ResumeInput
from resume_maker.sdk.services import Resumes

router = APIRouter(prefix="/api", tags=["resumes"])


@router.post("/resumes")
def new_resume(dep_resume: Annotated[Resumes, Depends(service("resume"))], body: ResumeInput):
    """创建新的简历组合，将项目经历引用固定到具体版本"""
    return dep_resume.save_resume(body.name, body.template_id, body.items, document=body.document)


@router.get("/resume-sources")
def resume_sources(dep_resume: Annotated[Resumes, Depends(service("resume"))]):
    """列出可加入简历的资料来源，缺包不删除已经采用的文字"""
    return dep_resume.source_catalog()


@router.get("/resume-source-items")
def resume_source_items(
    dep_resume: Annotated[Resumes, Depends(service("resume"))],
    provider: str,
    cursor: str | None = Query(default=None, max_length=1000),
    query: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
):
    """读取已核对来源内容，客户端选择后仍须正常保存草稿"""
    return dep_resume.source_items(provider, cursor, query, limit)


@router.put("/resumes/{resume_id}")
def save_resume(
    dep_resume: Annotated[Resumes, Depends(service("resume"))], resume_id: str, body: ResumeInput
):
    """校验项目、版本和亮点归属并以乐观锁保存固定版本组合"""
    return dep_resume.save_resume(
        body.name,
        body.template_id,
        body.items,
        resume_id,
        body.version,
        document=body.document,
    )


@router.delete("/resumes/{resume_id}")
def delete_resume(
    dep_resume: Annotated[Resumes, Depends(service("resume"))],
    resume_id: str,
    version: int = Query(ge=1),
):
    """删除指定版本的简历方案，历史导出和原始项目资料继续保留"""
    dep_resume.delete_resume(resume_id, version)
    return {"ok": True}
