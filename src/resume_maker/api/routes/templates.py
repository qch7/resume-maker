"""本机 Word 模板检查和登记的 HTTP 入口。"""

import re
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from resume_maker.api.dependencies import ServicesDep
from resume_maker.api.schemas import (
    AdaptiveTemplateInput,
    PathInput,
    TemplateAnalysisInput,
    TemplateInput,
    TemplatePreviewInput,
    TemplateRepairInput,
)
from resume_maker.core.errors import Problem
from resume_maker.integrations.word.ooxml import inspect_template
from resume_maker.integrations.word.template_map import TemplatePackage

router = APIRouter(prefix="/api", tags=["templates"])


@router.post("/templates/inspect")
def inspect(services: ServicesDep, body: PathInput):
    """读取本机 DOCX 结构，返回段落索引及建议替换区间。"""
    return inspect_template(Path(body.path).expanduser().resolve(strict=True))


@router.post("/templates")
def import_template(services: ServicesDep, body: TemplateInput):
    """复制原模板并标记项目经历区域，登记模板哈希和区间映射。"""
    return services.documents.import_template(Path(body.path), body.name, body.start, body.end)


@router.post("/templates/analyses")
def analyze_template(services: ServicesDep, body: TemplateAnalysisInput):
    """启动可取消的模板语义分析，立即返回独立任务标识。"""
    return services.templates.analyze(Path(body.path), body.document, body.items)


@router.post("/templates/{template_id}/edit")
def edit_template(services: ServicesDep, template_id: str):
    """打开已保存完整模板的编辑副本，保留原模板版本及其所有简历引用。"""
    return services.templates.open(template_id)


@router.get("/templates/analyses/{analysis_id}")
def get_analysis(services: ServicesDep, analysis_id: str):
    """读取本实例分析进度、节点清单、建议映射及未处理内容。"""
    return services.templates.get(analysis_id)


@router.post("/templates/analyses/{analysis_id}/cancel")
def cancel_analysis(services: ServicesDep, analysis_id: str):
    """取消模板分析，禁止迟到结果覆盖取消状态。"""
    return services.templates.cancel(analysis_id)


@router.post("/templates/analyses/{analysis_id}/review")
def review_mapping(services: ServicesDep, analysis_id: str, body: TemplatePreviewInput):
    """重新验证修改后的字段与区域，返回仍需处理的具体内容。"""
    return services.templates.review(analysis_id, body.plan, body.document, body.items)


@router.post("/templates/analyses/{analysis_id}/repair")
def repair_mapping(services: ServicesDep, analysis_id: str, body: TemplateRepairInput):
    """让 AI 根据当前方案、校验问题和用户文字说明继续完善。"""
    return services.templates.repair(
        analysis_id, body.plan, body.document, body.items, body.feedback
    )


@router.get("/templates/analyses/{analysis_id}/images/{node_id}")
def template_image(services: ServicesDep, analysis_id: str, node_id: str):
    """以图片响应展示内嵌 PNG/JPEG/GIF，不执行模板内的脚本或外部资源。"""
    data = TemplatePackage(services.templates.source(analysis_id)).image(node_id)
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
def save_mapping(services: ServicesDep, analysis_id: str, body: AdaptiveTemplateInput):
    """保存用户确认的完整模板版本，不改变当前简历资料。"""
    return services.templates.save(analysis_id, body.name, body.plan, body.document, body.items)


@router.post("/templates/analyses/{analysis_id}/preview")
def preview_mapping(services: ServicesDep, analysis_id: str, body: TemplatePreviewInput):
    """使用当前资料生成试填 Word，并在渲染可用时返回真实页数。"""
    return services.templates.preview(analysis_id, body.plan, body.document, body.items)


@router.get("/templates/analyses/{analysis_id}/previews/{preview_id}/{file_name}")
def preview_file(services: ServicesDep, analysis_id: str, preview_id: str, file_name: str):
    """仅提供当前分析目录中的 Word、PDF 与分页图，不允许任意路径读取。"""
    try:
        UUID(preview_id)
    except ValueError as exc:
        raise Problem("预览标识无效。", 404) from exc
    if not re.fullmatch(r"resume\.(docx|pdf)|page-[1-9][0-9]*\.png", file_name):
        raise Problem("预览文件不存在。", 404)
    path = services.templates.source(analysis_id).parent / preview_id / file_name
    if not path.is_file():
        raise Problem("预览文件不存在。", 404)
    return FileResponse(path, filename=file_name)
