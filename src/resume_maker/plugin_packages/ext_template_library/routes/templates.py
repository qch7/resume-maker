"""本机 Word 模板检查和登记的 HTTP 入口"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from resume_maker.api.dependencies import service
from resume_maker.api.schemas import (
    TemplateCategoryInput,
    TemplateLibraryItemInput,
)
from resume_maker.sdk.services import TemplateLibrary

router = APIRouter(prefix="/api", tags=["templates"])


@router.get("/template-library")
def template_library(
    dep_template_library: Annotated[TemplateLibrary, Depends(service("template_library"))],
):
    """读取所有入口共用的模板分类和 Like"""
    return dep_template_library.state()


@router.patch("/template-library/items/{template_id}")
def update_library_item(
    dep_template_library: Annotated[TemplateLibrary, Depends(service("template_library"))],
    template_id: str,
    body: TemplateLibraryItemInput,
):
    """更新单个模板的组织信息"""
    return dep_template_library.update(template_id, body.model_dump(exclude_unset=True))


@router.post("/template-library/categories")
def create_template_category(
    dep_template_library: Annotated[TemplateLibrary, Depends(service("template_library"))],
    body: TemplateCategoryInput,
):
    """创建模板分类"""
    return dep_template_library.create_category(body.name)


@router.delete("/template-library/items/{template_id}")
def delete_library_template(
    dep_template_library: Annotated[TemplateLibrary, Depends(service("template_library"))],
    template_id: str,
    permanent: bool = False,
):
    """未引用模板先进入回收站，显式选择永久删除后清理保存数据"""
    return dep_template_library.delete(template_id, permanent=permanent)


@router.post("/template-library/items/{template_id}/restore")
def restore_library_template(
    dep_template_library: Annotated[TemplateLibrary, Depends(service("template_library"))],
    template_id: str,
):
    """从项目回收站恢复模板及原分类收藏"""
    return dep_template_library.restore(template_id)


@router.delete("/template-library/categories/{category_id}")
def delete_template_category(
    dep_template_library: Annotated[TemplateLibrary, Depends(service("template_library"))],
    category_id: str,
):
    """移除分类并将其中模板恢复为未分类"""
    return dep_template_library.delete_category(category_id)


@router.get("/template-library/items/{template_id}/thumbnail")
def template_thumbnail(
    dep_template_library: Annotated[TemplateLibrary, Depends(service("template_library"))],
    template_id: str,
):
    """提供受实例令牌保护的真实模板首屏图片"""
    return FileResponse(dep_template_library.thumbnail(template_id), media_type="image/png")
