"""固定版本简历组合与导出下载的 HTTP 入口。"""

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from resume_maker.api.dependencies import ServicesDep
from resume_maker.api.schemas import ResumeInput
from resume_maker.core.errors import Problem, need

router = APIRouter(prefix="/api", tags=["resumes"])


@router.post("/resumes")
def new_resume(services: ServicesDep, body: ResumeInput):
    """创建新的简历组合，将项目经历引用固定到具体版本。"""
    return services.catalog.save_resume(body.name, body.template_id, body.items)


@router.put("/resumes/{resume_id}")
def save_resume(services: ServicesDep, resume_id: str, body: ResumeInput):
    """校验项目、版本与亮点归属，并以乐观锁保存固定版本组合。"""
    return services.catalog.save_resume(
        body.name, body.template_id, body.items, resume_id, body.version
    )


@router.post("/resumes/{resume_id}/exports")
def export(services: ServicesDep, resume_id: str):
    """读取固定版本组合，替换模板经历区并保存 DOCX、预览和追溯清单。"""
    return services.documents.export(resume_id)


@router.delete("/resumes/{resume_id}")
def delete_resume(services: ServicesDep, resume_id: str, version: int = Query(ge=1)):
    """删除指定版本的简历方案，历史导出和原始项目资料继续保留。"""
    services.catalog.delete_resume(resume_id, version)
    return {"ok": True}


@router.get("/resumes/{resume_id}/exports")
def export_history(services: ServicesDep, resume_id: str):
    """列出指定简历的历史导出，让重新打开页面时可恢复上次预览。"""
    return services.db.all(
        "SELECT * FROM exports WHERE resume_id=? ORDER BY created_at DESC", (resume_id,)
    )


@router.get("/exports/{export_id}/{file_name}")
def export_file(services: ServicesDep, export_id: str, file_name: str):
    """仅允许下载本次导出登记的 DOCX、PDF、清单或有效页码图片。"""
    record = need(services.db.one("SELECT * FROM exports WHERE id=?", (export_id,)))
    allowed = {"resume.docx", "resume.pdf", "manifest.json"}
    allowed.update(f"page-{i}.png" for i in range(1, (record["pages"] or 0) + 1))
    if file_name not in allowed:
        raise Problem("文件不存在。", 404)
    path = services.config.data_dir / "exports" / export_id / file_name
    if not path.exists():
        raise Problem("该文件尚未生成。", 404)
    return FileResponse(path, filename=file_name)
