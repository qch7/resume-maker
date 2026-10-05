"""本机 Word 模板检查和登记的 HTTP 入口"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from resume_maker.api.dependencies import service
from resume_maker.api.schemas import (
    TemplateAnalysisInput,
)
from resume_maker.sdk.services import Templates

router = APIRouter(prefix="/api", tags=["templates"])


@router.post("/templates/analyses")
def analyze_template(
    dep_templates: Annotated[Templates, Depends(service("templates"))], body: TemplateAnalysisInput
):
    """启动可取消的模板分析并返回任务标识"""
    return dep_templates.analyze(
        Path(body.path), body.document, body.items, importer_id=body.importer_id
    )
