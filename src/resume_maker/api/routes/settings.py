"""Provider 配置与实际连接检查的 HTTP 入口。"""

import threading

from fastapi import APIRouter

from resume_maker.api.dependencies import ServicesDep
from resume_maker.domain.models import ProviderSettings
from resume_maker.infrastructure.database import uid
from resume_maker.integrations.providers.codex import CodexProvider

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
def settings(
    services: ServicesDep,
):
    """返回 Provider 设置和数据目录，未配置的字段使用默认值。"""
    return {
        "provider": services.db.setting("provider", ProviderSettings().model_dump()),
        "data_dir": str(services.config.data_dir),
    }


@router.put("/settings/provider")
def provider_settings(services: ServicesDep, body: ProviderSettings):
    """保存经过模型校验的 Provider 参数，供后续任务读取。"""
    services.db.set_setting("provider", body.model_dump())
    return body


@router.get("/providers/codex")
def inspect_provider(
    services: ServicesDep,
):
    """检查当前配置的 Codex CLI 是否可执行并返回版本信息。"""
    return CodexProvider().inspect(
        ProviderSettings.model_validate(services.db.setting("provider", {}))
    )


@router.post("/providers/codex/check")
def check_provider(
    services: ServicesDep,
):
    """发起最小结构化连接请求，以真实响应确认当前 Provider 配置可用。"""
    result = CodexProvider().run(
        workspace=services.config.data_dir / "workspaces" / f"check-{uid()}",
        prompt="连接测试。不要使用工具或读取文件。reply 写连接成功；"
        "experience=null，changes=[]，questions=[]。",
        thread_id=None,
        settings=ProviderSettings.model_validate(services.db.setting("provider", {})),
        cancelled=threading.Event(),
        emit=lambda *_: None,
    )
    return {"ok": True, "reply": result.reply}
