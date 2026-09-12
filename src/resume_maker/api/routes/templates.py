"""本机 Word 模板检查和登记的 HTTP 入口。"""

from pathlib import Path

from fastapi import APIRouter

from resume_maker.api.dependencies import ServicesDep
from resume_maker.api.schemas import PathInput, TemplateInput
from resume_maker.integrations.word.ooxml import inspect_template

router = APIRouter(prefix="/api", tags=["templates"])


@router.post("/templates/inspect")
def inspect(services: ServicesDep, body: PathInput):
    """读取本机 DOCX 结构，返回段落索引及建议替换区间。"""
    return inspect_template(Path(body.path).expanduser().resolve(strict=True))


@router.post("/templates")
def import_template(services: ServicesDep, body: TemplateInput):
    """复制原模板并标记项目经历区域，登记模板哈希和区间映射。"""
    return services.documents.import_template(Path(body.path), body.name, body.start, body.end)
