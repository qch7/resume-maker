"""Provider 配置和实际连接检查的 HTTP 入口"""

from typing import Annotated

from fastapi import APIRouter, Depends

from resume_maker.api.dependencies import service
from resume_maker.domain.resume_defaults import ResumeDefaults
from resume_maker.sdk.services import Settings

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings/resume-defaults")
def resume_defaults(dep_settings: Annotated[Settings, Depends(service("settings"))]):
    """读取本机保存的默认栏目，未设置时由界面提供内置初始配置"""
    return dep_settings.resume_defaults()


@router.put("/settings/resume-defaults")
def save_resume_defaults(
    dep_settings: Annotated[Settings, Depends(service("settings"))], body: ResumeDefaults
):
    """原子校验配置版本，保存后供新简历使用且随数据库备份"""
    return dep_settings.save_resume_defaults(body)


@router.get("/settings")
def settings(
    dep_settings: Annotated[Settings, Depends(service("settings"))],
):
    """返回 Provider 设置和数据目录，未配置的字段使用默认值"""
    return dep_settings.get()
