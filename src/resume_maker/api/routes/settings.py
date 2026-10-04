"""Provider 配置和实际连接检查的 HTTP 入口"""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends

from resume_maker.api.dependencies import service
from resume_maker.domain.models import ProviderSettings
from resume_maker.domain.recruitment import RecruitmentPreferences
from resume_maker.domain.resume_defaults import ResumeDefaults
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


@router.put("/settings/provider")
def provider_settings(
    dep_settings: Annotated[Settings, Depends(service("settings"))], body: ProviderSettings
):
    """保存经过模型校验的 Provider 参数，供后续任务读取"""
    return dep_settings.save_provider(body)


@router.get("/providers/codex")
def inspect_provider(
    dep_settings: Annotated[Settings, Depends(service("settings"))],
    dep_inspect: Annotated[Callable, Depends(service("model.inspection"))],
):
    """检查当前配置的 Codex CLI 是否可执行并返回版本信息"""
    return dep_inspect(ProviderSettings.model_validate(dep_settings.get()["provider"]))


@router.post("/providers/codex/check")
def check_provider(
    dep_settings: Annotated[Settings, Depends(service("settings"))],
):
    """发起最小结构化连接请求，以真实响应确认当前 Provider 配置可用"""
    return dep_settings.check_provider()
