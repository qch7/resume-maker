"""Provider 配置和实际连接检查的 HTTP 入口"""

from typing import Annotated

from fastapi import APIRouter, Depends

from resume_maker.api.dependencies import service
from resume_maker.domain.recruitment import RecruitmentPreferences
from resume_maker.sdk.services import Settings

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings/recruitment")
def recruitment_settings(dep_settings: Annotated[Settings, Depends(service("settings"))]):
    """读取招聘收藏夹的独立导入设置"""
    return dep_settings.recruitment()


@router.put("/settings/recruitment")
def save_recruitment_settings(
    dep_settings: Annotated[Settings, Depends(service("settings"))], body: RecruitmentPreferences
):
    """校验并保存收藏夹导入偏好"""
    return dep_settings.save_recruitment(body)
