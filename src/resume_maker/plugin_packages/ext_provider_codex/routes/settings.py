"""Provider 配置和实际连接检查的 HTTP 入口"""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends

from resume_maker.api.dependencies import service
from resume_maker.domain.models import ProviderSettings
from resume_maker.sdk.services import Settings

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/providers/codex")
def inspect_provider(
    dep_settings: Annotated[Settings, Depends(service("settings"))],
    dep_inspect: Annotated[Callable, Depends(service("model.inspection"))],
):
    """检查当前配置的 Codex CLI 是否可执行并返回版本信息"""
    return dep_inspect(ProviderSettings.model_validate(dep_settings.get()["provider"]))
