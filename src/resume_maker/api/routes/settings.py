"""Provider 配置和实际连接检查的 HTTP 入口"""

from fastapi import APIRouter

from resume_maker.api.dependencies import ServicesDep
from resume_maker.domain.models import ProviderSettings
from resume_maker.domain.resume_defaults import ResumeDefaults

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings/resume-defaults")
def resume_defaults(services: ServicesDep):
    """读取本机保存的默认栏目，未设置时由界面提供内置初始配置"""
    return services.settings.resume_defaults()


@router.put("/settings/resume-defaults")
def save_resume_defaults(services: ServicesDep, body: ResumeDefaults):
    """原子校验配置版本，保存后供新简历使用且随数据库备份"""
    return services.settings.save_resume_defaults(body)


@router.get("/settings")
def settings(
    services: ServicesDep,
):
    """返回 Provider 设置和数据目录，未配置的字段使用默认值"""
    return services.settings.get()


@router.put("/settings/provider")
def provider_settings(services: ServicesDep, body: ProviderSettings):
    """保存经过模型校验的 Provider 参数，供后续任务读取"""
    return services.settings.save_provider(body)


@router.get("/providers/codex")
def inspect_provider(
    services: ServicesDep,
):
    """检查当前配置的 Codex CLI 是否可执行并返回版本信息"""
    return services.settings.inspect_provider()


@router.post("/providers/codex/check")
def check_provider(
    services: ServicesDep,
):
    """发起最小结构化连接请求，以真实响应确认当前 Provider 配置可用"""
    return services.settings.check_provider()
