"""本机隐私规则、脱敏预览及有界发送记录接口"""

from fastapi import APIRouter
from pydantic import Field

from resume_maker.api.dependencies import ServicesDep
from resume_maker.domain.models import Model

router = APIRouter(prefix="/api/privacy", tags=["privacy"])


class PrivacyTerms(Model):
    """用户补充的准确敏感值，只保存在当前实例的本机数据库"""

    terms: list[str] = Field(max_length=300)
    version: int = Field(default=0, ge=0)


class PrivacyPreview(Model):
    """只在本机检测一段文字，不触发任何供应商请求"""

    text: str = Field(max_length=30000)


@router.get("")
def privacy(services: ServicesDep):
    """返回强制隐私策略及用户可补充的敏感词"""
    return services.privacy.get()


@router.put("/terms")
def save_terms(services: ServicesDep, body: PrivacyTerms):
    """规范化并保存有界敏感词，后续每轮请求自动加载新规则"""
    return services.privacy.save_terms(body.terms, body.version)


@router.post("/preview")
def preview(services: ServicesDep, body: PrivacyPreview):
    """预览和发送共用脱敏引擎，预览正文及映射不保存"""
    return services.privacy.preview(body.text)


@router.get("/requests")
def requests(services: ServicesDep):
    """只返回已脱敏的请求体，响应正文和真实值映射不会进入记录"""
    return services.privacy.requests()


@router.delete("/requests")
def clear_requests(services: ServicesDep):
    """清除当前实例的发送记录，不改动真实简历或敏感词"""
    return services.privacy.clear_requests()
