"""荣誉条目、受鉴权保护的文件上传和证书预览入口"""

from typing import Annotated

from fastapi import APIRouter, Depends

from resume_maker.api.dependencies import service
from resume_maker.sdk.services import Honors

router = APIRouter(prefix="/api/honors", tags=["honors"])


@router.post("/{honor_id}/recognize")
def recognize_honor(dep_honors: Annotated[Honors, Depends(service("honors"))], honor_id: str):
    """按当前设置重新识别已有原件"""
    return dep_honors.recognize(honor_id)
