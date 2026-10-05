"""招聘收藏夹页面的保存、交换文件和导入预览入口"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import Field

from resume_maker.api.dependencies import service
from resume_maker.domain.models import Model
from resume_maker.domain.recruitment import RecruitmentFile
from resume_maker.sdk.services import Recruitment

router = APIRouter(prefix="/api/recruitment", tags=["recruitment"])


class SaveBookmarks(Model):
    """保存版本属于本机，交换文件仅保留格式版本"""

    revision: int = Field(ge=0)
    data: RecruitmentFile


class ImportBookmarks(Model):
    """同一文件和冲突策略用于预览和确认，旧预览不能覆盖新数据"""

    revision: int = Field(ge=0)
    content: str = Field(max_length=8_000_000)
    policy: Literal["keep", "update"] = "keep"


def json_download(content: str, name: str):
    """用 UTF-8 JSON 附件下载交换文件"""
    return Response(
        content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}.bookmarks.json"'},
    )


@router.get("")
def bookmarks(dep_recruitment: Annotated[Recruitment, Depends(service("recruitment"))]):
    """读取当前数据目录的独立收藏夹"""
    return dep_recruitment.get()


@router.put("")
def save_bookmarks(
    dep_recruitment: Annotated[Recruitment, Depends(service("recruitment"))], body: SaveBookmarks
):
    """保存通过格式和引用校验的用户修改"""
    return dep_recruitment.save(body.revision, body.data)


@router.post("/import/preview")
def preview_import(
    dep_recruitment: Annotated[Recruitment, Depends(service("recruitment"))], body: ImportBookmarks
):
    """返回新增、更新和跳过的条目，预览不改变数据库"""
    return dep_recruitment.import_file(body.revision, body.content, body.policy, preview=True)


@router.post("/import")
def import_bookmarks(
    dep_recruitment: Annotated[Recruitment, Depends(service("recruitment"))], body: ImportBookmarks
):
    """用户确认后重新校验版本并一次合并全部有效条目"""
    return dep_recruitment.import_file(body.revision, body.content, body.policy, preview=False)


@router.get("/export")
def export_bookmarks(dep_recruitment: Annotated[Recruitment, Depends(service("recruitment"))]):
    """导出全部领域、收藏、链接和备注，保留稳定标识和顺序"""
    data = RecruitmentFile.model_validate(dep_recruitment.get()["data"])
    return json_download(data.model_dump_json(indent=2), "recruitment")
