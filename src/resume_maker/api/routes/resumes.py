"""固定版本简历组合和导出下载的 HTTP 入口"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response

from resume_maker.api.dependencies import service
from resume_maker.api.resources import AssetResponse
from resume_maker.api.schemas import ResumeInput, ResumePreviewInput
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem, need
from resume_maker.infrastructure.assets import Assets
from resume_maker.infrastructure.database import Database
from resume_maker.sdk.records import dump
from resume_maker.sdk.services import Documents, ResumePreviews, Resumes

router = APIRouter(prefix="/api", tags=["resumes"])


@router.post("/resume-previews")
def preview_resume(
    dep_resume_previews: Annotated[ResumePreviews, Depends(service("resume_previews"))],
    body: ResumePreviewInput,
    engine_id: str | None = None,
    renderer_id: str | None = None,
):
    """用当前模板为未保存资料生成临时预览"""
    return dep_resume_previews.render(
        body.template_id,
        body.document.model_dump(),
        [item.model_dump() for item in body.items],
        engine_id=engine_id,
        renderer_id=renderer_id,
    )


@router.get("/resume-previews/{preview_id}/{file_name}")
def preview_file(
    dep_resume_previews: Annotated[ResumePreviews, Depends(service("resume_previews"))],
    preview_id: str,
    file_name: str,
):
    """鉴权后返回本实例已生成的 Word 预览"""
    return FileResponse(dep_resume_previews.file(preview_id, file_name), filename=file_name)


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


@router.post("/resumes/{resume_id}/exports")
def export(
    dep_documents: Annotated[Documents, Depends(service("documents"))],
    resume_id: str,
    engine_id: str | None = None,
    renderer_id: str | None = None,
):
    """读取固定版本组合，生成完整简历 Word、预览和追溯清单"""
    return dep_documents.export(resume_id, engine_id=engine_id, renderer_id=renderer_id)


@router.get("/document-engines")
def document_engines(dep_documents: Annotated[Documents, Depends(service("documents"))]):
    """向插件客户端提供可选引擎，不按加载顺序替换默认实现"""
    return dep_documents.engines()


@router.get("/document-importers")
def document_importers(
    dep_documents: Annotated[Documents, Depends(service("documents"))], purpose: str = "template"
):
    """公开已启用的格式和处理器，上传时仍须探测实际内容"""
    return dep_documents.importers(purpose)


@router.delete("/resumes/{resume_id}")
def delete_resume(
    dep_resume: Annotated[Resumes, Depends(service("resume"))],
    resume_id: str,
    version: int = Query(ge=1),
):
    """删除指定版本的简历方案，历史导出和原始项目资料继续保留"""
    dep_resume.delete_resume(resume_id, version)
    return {"ok": True}


@router.get("/resumes/{resume_id}/exports")
def export_history(dep_db: Annotated[Database, Depends(service("db"))], resume_id: str):
    """列出指定简历的历史导出，让重新打开页面时可恢复上次预览"""
    return dep_db.all(
        "SELECT * FROM exports WHERE resume_id=? ORDER BY created_at DESC", (resume_id,)
    )


@router.get("/exports/{export_id}/{file_name}")
def export_file(
    dep_assets: Annotated[Assets, Depends(service("assets"))],
    dep_config: Annotated[Config, Depends(service("config"))],
    dep_db: Annotated[Database, Depends(service("db"))],
    export_id: str,
    file_name: str,
):
    """仅允许下载本次导出登记的 DOCX、PDF、清单或有效页码图片"""
    record = need(dep_db.one("SELECT * FROM exports WHERE id=?", (export_id,)))
    allowed = {"resume.docx", "resume.pdf", "manifest.json"}
    allowed.update(f"page-{i}.png" for i in range(1, (record["pages"] or 0) + 1))
    if file_name not in allowed:
        raise Problem("文件不存在。", 404)
    if file_name == "manifest.json":
        return Response(
            dump(record["manifest"]),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="manifest.json"'},
        )
    if asset_id := record["manifest"].get("assets", {}).get(file_name):
        return AssetResponse(dep_assets, asset_id, file_name)
    path = dep_config.data_dir / "exports" / export_id / file_name
    if not path.exists():
        raise Problem("该文件尚未生成。", 404)
    return FileResponse(path, filename=file_name)
