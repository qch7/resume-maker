"""本机隐私规则、脱敏预览及有界发送记录接口"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import Field

from resume_maker.api.dependencies import service
from resume_maker.domain.models import Model
from resume_maker.sdk.services import Privacy

router = APIRouter(prefix="/api/privacy", tags=["privacy"])


class PrivacyTerms(Model):
    """用户补充的准确敏感值，只保存在当前实例的本机数据库"""

    terms: list[str] = Field(max_length=300)
    version: int = Field(default=0, ge=0)


class PrivacyPreview(Model):
    """只在本机检测一段文字，不触发任何供应商请求"""

    text: str = Field(max_length=30000)


@router.get("")
def privacy(dep_privacy: Annotated[Privacy, Depends(service("privacy"))]):
    """返回强制隐私策略及用户可补充的敏感词"""
    return dep_privacy.get()


@router.put("/terms")
def save_terms(dep_privacy: Annotated[Privacy, Depends(service("privacy"))], body: PrivacyTerms):
    """规范化并保存有界敏感词，后续每轮请求自动加载新规则"""
    return dep_privacy.save_terms(body.terms, body.version)


@router.post("/preview")
def preview(dep_privacy: Annotated[Privacy, Depends(service("privacy"))], body: PrivacyPreview):
    """预览和发送共用脱敏引擎，预览正文及映射不保存"""
    return dep_privacy.preview(body.text)


@router.get("/requests")
def requests(dep_privacy: Annotated[Privacy, Depends(service("privacy"))]):
    """只返回已脱敏的请求体，响应正文和真实值映射不会进入记录"""
    return dep_privacy.requests()


@router.delete("/requests")
def clear_requests(dep_privacy: Annotated[Privacy, Depends(service("privacy"))]):
    """清除当前实例的发送记录，不改动真实简历或敏感词"""
    return dep_privacy.clear_requests()
