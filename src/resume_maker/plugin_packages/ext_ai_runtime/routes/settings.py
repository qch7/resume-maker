"""Provider 配置和实际连接检查的 HTTP 入口"""

from typing import Annotated

from fastapi import APIRouter, Depends

from resume_maker.api.dependencies import service
from resume_maker.domain.models import ProviderSettings
from resume_maker.sdk.services import Settings

router = APIRouter(prefix="/api", tags=["settings"])


@router.put("/settings/provider")
def provider_settings(
    dep_settings: Annotated[Settings, Depends(service("settings"))], body: ProviderSettings
):
    """保存经过模型校验的 Provider 参数，供后续任务读取"""
    return dep_settings.save_provider(body)


@router.post("/providers/codex/check")
def check_provider(
    dep_settings: Annotated[Settings, Depends(service("settings"))],
):
    """发起最小结构化连接请求，以真实响应确认当前 Provider 配置可用"""
    return dep_settings.check_provider()
