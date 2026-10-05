"""本机 Word 模板检查和登记的 HTTP 入口"""

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response

from resume_maker.api.dependencies import service
from resume_maker.api.schemas import (
    AdaptiveTemplateInput,
    TemplateEditInput,
    TemplatePreviewInput,
    TemplateRepairInput,
)
from resume_maker.core.errors import Problem
from resume_maker.integrations.word.templates.mapping import TemplatePackage
from resume_maker.sdk.services import Templates

router = APIRouter(prefix="/api", tags=["templates"])


@router.get("/templates/analyses")
def list_analyses(dep_templates: Annotated[Templates, Depends(service("templates"))]):
    """列出已留存的模板分析及人工核对工作"""
    return dep_templates.list_tasks()


@router.post("/templates/analyses/{analysis_id}/retry")
def retry_analysis(
    dep_templates: Annotated[Templates, Depends(service("templates"))],
    analysis_id: str,
    body: TemplateEditInput,
):
    """显式使用保存的原件重新分析，中断不会丢失输入文件"""
    return dep_templates.retry(analysis_id, body.document, body.items)


@router.post("/templates/{template_id}/edit")
def edit_template(
    dep_templates: Annotated[Templates, Depends(service("templates"))],
    template_id: str,
    body: TemplateEditInput | None = None,
):
    """按当前资料打开并补齐独立副本，保留原模板版本及其所有简历引用"""
    return dep_templates.open(
        template_id, body.document if body else None, body.items if body else None
    )


@router.get("/templates/analyses/{analysis_id}")
def get_analysis(
    dep_templates: Annotated[Templates, Depends(service("templates"))], analysis_id: str
):
    """读取本实例分析进度、节点清单、建议映射及未处理内容"""
    return dep_templates.get(analysis_id)


@router.get("/templates/analyses/{analysis_id}/progress")
def analysis_progress(
    dep_templates: Annotated[Templates, Depends(service("templates"))],
    analysis_id: str,
    after: int = Query(0, ge=0),
):
    """读取轻量状态和新增公开活动以免轮询时重复传输整份模板"""
    return dep_templates.progress(analysis_id, after)


@router.post("/templates/analyses/{analysis_id}/cancel")
def cancel_analysis(
    dep_templates: Annotated[Templates, Depends(service("templates"))], analysis_id: str
):
    """取消模板分析，禁止迟到结果覆盖取消状态"""
    return dep_templates.cancel(analysis_id)


@router.post("/templates/analyses/{analysis_id}/review")
def review_mapping(
    dep_templates: Annotated[Templates, Depends(service("templates"))],
    analysis_id: str,
    body: TemplatePreviewInput,
):
    """重新验证修改后的字段和区域，返回仍需处理的具体内容"""
    return dep_templates.review(analysis_id, body.plan, body.document, body.items)


@router.post("/templates/analyses/{analysis_id}/repair")
def repair_mapping(
    dep_templates: Annotated[Templates, Depends(service("templates"))],
    analysis_id: str,
    body: TemplateRepairInput,
):
    """让 AI 根据当前方案、校验问题和用户文字说明继续完善"""
    return dep_templates.repair(analysis_id, body.plan, body.document, body.items, body.feedback)


@router.get("/templates/analyses/{analysis_id}/images/{node_id}")
def template_image(
    dep_templates: Annotated[Templates, Depends(service("templates"))],
    analysis_id: str,
    node_id: str,
):
    """仅以图片响应展示模板内嵌的 PNG、JPEG 或 GIF"""
    data = TemplatePackage(dep_templates.source(analysis_id)).image(node_id)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        media_type = "image/jpeg"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        media_type = "image/gif"
    else:
        raise Problem("此图片格式请在原 Word 中核对。", 415)
    return Response(data, media_type=media_type, headers={"X-Content-Type-Options": "nosniff"})


@router.post("/templates/analyses/{analysis_id}/save")
def save_mapping(
    dep_templates: Annotated[Templates, Depends(service("templates"))],
    analysis_id: str,
    body: AdaptiveTemplateInput,
):
    """保存用户确认的完整模板版本"""
    return dep_templates.save(analysis_id, body.name, body.plan, body.document, body.items)


@router.post("/templates/analyses/{analysis_id}/preview")
def preview_mapping(
    dep_templates: Annotated[Templates, Depends(service("templates"))],
    analysis_id: str,
    body: TemplatePreviewInput,
):
    """使用当前资料生成试填 Word并在渲染可用时返回真实页数"""
    return dep_templates.preview(analysis_id, body.plan, body.document, body.items)


@router.get("/templates/analyses/{analysis_id}/previews/{preview_id}/{file_name}")
def preview_file(
    dep_templates: Annotated[Templates, Depends(service("templates"))],
    analysis_id: str,
    preview_id: str,
    file_name: str,
):
    """仅提供当前分析目录中的 Word、PDF 和分页图"""
    try:
        UUID(preview_id)
    except ValueError as exc:
        raise Problem("预览标识无效。", 404) from exc
    if not re.fullmatch(r"resume\.(docx|pdf)|page-[1-9][0-9]*\.(png|svg)", file_name):
        raise Problem("预览文件不存在。", 404)
    path = dep_templates.source(analysis_id).parent / preview_id / file_name
    if not path.is_file():
        raise Problem("预览文件不存在。", 404)
    return FileResponse(path, filename=file_name)
