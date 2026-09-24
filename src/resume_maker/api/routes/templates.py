"""本机 Word 模板检查和登记的 HTTP 入口"""

import re
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response

from resume_maker.api.dependencies import ServicesDep
from resume_maker.api.schemas import (
    AdaptiveTemplateInput,
    TemplateAnalysisInput,
    TemplateCategoryInput,
    TemplateEditInput,
    TemplateLibraryItemInput,
    TemplatePreviewInput,
    TemplateRepairInput,
)
from resume_maker.core.errors import Problem
from resume_maker.integrations.word.templates.mapping import TemplatePackage

router = APIRouter(prefix="/api", tags=["templates"])


@router.get("/template-library")
def template_library(services: ServicesDep):
    """读取所有入口共用的模板分类和 Like"""
    return services.template_library.state()


@router.patch("/template-library/items/{template_id}")
def update_library_item(services: ServicesDep, template_id: str, body: TemplateLibraryItemInput):
    """更新单个模板的组织信息"""
    return services.template_library.update(template_id, body.model_dump(exclude_unset=True))


@router.post("/template-library/categories")
def create_template_category(services: ServicesDep, body: TemplateCategoryInput):
    """创建模板分类"""
    return services.template_library.create_category(body.name)


@router.delete("/template-library/items/{template_id}")
def delete_library_template(services: ServicesDep, template_id: str, permanent: bool = False):
    """未引用模板先进入回收站，显式选择永久删除后清理保存数据"""
    return services.template_library.delete(template_id, permanent=permanent)


@router.post("/template-library/items/{template_id}/restore")
def restore_library_template(services: ServicesDep, template_id: str):
    """从项目回收站恢复模板及原分类收藏"""
    return services.template_library.restore(template_id)


@router.delete("/template-library/categories/{category_id}")
def delete_template_category(services: ServicesDep, category_id: str):
    """移除分类并将其中模板恢复为未分类"""
    return services.template_library.delete_category(category_id)


@router.get("/template-library/items/{template_id}/thumbnail")
def template_thumbnail(services: ServicesDep, template_id: str):
    """提供受实例令牌保护的真实模板首屏图片"""
    return FileResponse(services.template_library.thumbnail(template_id), media_type="image/png")


@router.post("/templates/analyses")
def analyze_template(services: ServicesDep, body: TemplateAnalysisInput):
    """启动可取消的模板分析并返回任务标识"""
    return services.templates.analyze(Path(body.path), body.document, body.items)


@router.get("/templates/analyses")
def list_analyses(services: ServicesDep):
    """列出已留存的模板分析及人工核对工作"""
    return services.templates.list_tasks()


@router.post("/templates/analyses/{analysis_id}/retry")
def retry_analysis(services: ServicesDep, analysis_id: str, body: TemplateEditInput):
    """显式使用保存的原件重新分析，中断不会丢失输入文件"""
    return services.templates.retry(analysis_id, body.document, body.items)


@router.post("/templates/{template_id}/edit")
def edit_template(services: ServicesDep, template_id: str, body: TemplateEditInput | None = None):
    """按当前资料打开并补齐独立副本，保留原模板版本及其所有简历引用"""
    return services.templates.open(
        template_id, body.document if body else None, body.items if body else None
    )


@router.get("/templates/analyses/{analysis_id}")
def get_analysis(services: ServicesDep, analysis_id: str):
    """读取本实例分析进度、节点清单、建议映射及未处理内容"""
    return services.templates.get(analysis_id)


@router.get("/templates/analyses/{analysis_id}/progress")
def analysis_progress(services: ServicesDep, analysis_id: str, after: int = Query(0, ge=0)):
    """读取轻量状态和新增公开活动以免轮询时重复传输整份模板"""
    return services.templates.progress(analysis_id, after)


@router.post("/templates/analyses/{analysis_id}/cancel")
def cancel_analysis(services: ServicesDep, analysis_id: str):
    """取消模板分析，禁止迟到结果覆盖取消状态"""
    return services.templates.cancel(analysis_id)


@router.post("/templates/analyses/{analysis_id}/review")
def review_mapping(services: ServicesDep, analysis_id: str, body: TemplatePreviewInput):
    """重新验证修改后的字段和区域，返回仍需处理的具体内容"""
    return services.templates.review(analysis_id, body.plan, body.document, body.items)


@router.post("/templates/analyses/{analysis_id}/repair")
def repair_mapping(services: ServicesDep, analysis_id: str, body: TemplateRepairInput):
    """让 AI 根据当前方案、校验问题和用户文字说明继续完善"""
    return services.templates.repair(
        analysis_id, body.plan, body.document, body.items, body.feedback
    )


@router.get("/templates/analyses/{analysis_id}/images/{node_id}")
def template_image(services: ServicesDep, analysis_id: str, node_id: str):
    """仅以图片响应展示模板内嵌的 PNG、JPEG 或 GIF"""
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
    """保存用户确认的完整模板版本"""
    return services.templates.save(analysis_id, body.name, body.plan, body.document, body.items)


@router.post("/templates/analyses/{analysis_id}/preview")
def preview_mapping(services: ServicesDep, analysis_id: str, body: TemplatePreviewInput):
    """使用当前资料生成试填 Word并在渲染可用时返回真实页数"""
    return services.templates.preview(analysis_id, body.plan, body.document, body.items)


@router.get("/templates/analyses/{analysis_id}/previews/{preview_id}/{file_name}")
def preview_file(services: ServicesDep, analysis_id: str, preview_id: str, file_name: str):
    """仅提供当前分析目录中的 Word、PDF 和分页图"""
    try:
        UUID(preview_id)
    except ValueError as exc:
        raise Problem("预览标识无效。", 404) from exc
    if not re.fullmatch(r"resume\.(docx|pdf)|page-[1-9][0-9]*\.(png|svg)", file_name):
        raise Problem("预览文件不存在。", 404)
    path = services.templates.source(analysis_id).parent / preview_id / file_name
    if not path.is_file():
        raise Problem("预览文件不存在。", 404)
    return FileResponse(path, filename=file_name)
