"""本机隐私规则、脱敏预览及有界发送记录接口"""

from fastapi import APIRouter
from pydantic import Field

from resume_maker.api.dependencies import ServicesDep
from resume_maker.core.errors import Problem
from resume_maker.domain.models import Model
from resume_maker.infrastructure.database import dump
from resume_maker.integrations.privacy_store import PrivacyStore

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
    saved = {
        row["key"]: row["value"]
        for row in services.db.all(
            "SELECT key,value_json FROM settings "
            "WHERE key IN ('privacy_terms','privacy_terms_version')"
        )
    }
    return {
        "enabled": True,
        "transport": "codex-cli-sandbox",
        "isolation": "read-only-material-tools",
        "images": "local-ocr",
        "ocr": {
            "engine": "RapidOCR / PP-OCRv4 mobile",
            "device": "CPU",
            "threads": 2,
            "base_side": 960,
            "retry_side": 2000,
        },
        "terms": saved.get("privacy_terms", []),
        "version": saved.get("privacy_terms_version", 0),
    }


@router.put("/terms")
def save_terms(services: ServicesDep, body: PrivacyTerms):
    """规范化并保存有界敏感词，后续每轮请求自动加载新规则"""
    terms = list(dict.fromkeys(value.strip() for value in body.terms if value.strip()))
    if any(len(value) > 500 for value in terms):
        raise Problem("单条敏感词最多 500 个字符。")
    with services.db.transaction() as conn:
        row = conn.execute(
            "SELECT value_json FROM settings WHERE key='privacy_terms_version'"
        ).fetchone()
        version = int(row[0]) if row else 0
        if version != body.version:
            raise Problem("敏感词已在其他窗口修改，请重新打开设置后再保存。", 409)
        conn.executemany(
            "INSERT OR REPLACE INTO settings VALUES (?,?)",
            [("privacy_terms", dump(terms)), ("privacy_terms_version", dump(version + 1))],
        )
    return {"terms": terms, "version": version + 1}


@router.post("/preview")
def preview(services: ServicesDep, body: PrivacyPreview):
    """预览和发送共用脱敏引擎，预览正文及映射不保存"""
    redactor = PrivacyStore(services.db).redactor()
    return {"text": redactor.prompt(body.text), "replacements": redactor.count}


@router.get("/requests")
def requests(services: ServicesDep):
    """只返回已脱敏的请求体，响应正文和真实值映射不会进入记录"""
    return services.db.setting("privacy_audit", [])


@router.delete("/requests")
def clear_requests(services: ServicesDep):
    """清除当前实例的发送记录，不改动真实简历或敏感词"""
    services.db.set_setting("privacy_audit", [])
    return {"cleared": True}
