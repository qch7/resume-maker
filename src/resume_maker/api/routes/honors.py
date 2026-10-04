"""荣誉条目、受鉴权保护的文件上传和证书预览入口"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from resume_maker.api.dependencies import service
from resume_maker.core.errors import Problem
from resume_maker.domain.honors import HonorSave
from resume_maker.integrations.certificates import MAX_BYTES
from resume_maker.sdk.services import Honors

router = APIRouter(prefix="/api/honors", tags=["honors"])


@router.get("")
def list_honors(dep_honors: Annotated[Honors, Depends(service("honors"))]):
    """列出持久化荣誉库"""
    return dep_honors.list()


@router.post("")
def create_honor(dep_honors: Annotated[Honors, Depends(service("honors"))], body: HonorSave):
    """手动添加没有附件的荣誉"""
    return dep_honors.save(body)


@router.post(
    "/upload",
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload_honor(
    request: Request,
    dep_honors: Annotated[Honors, Depends(service("honors"))],
    filename: str = Query(min_length=1, max_length=240),
    importer_id: str | None = None,
):
    """流式接收一个原件，先限制实际字节数，再在工作线程解码和入队"""
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_BYTES:
            raise Problem("单个证书文件不得超过 20 MB。", 413)
        content.extend(chunk)
    return await run_in_threadpool(dep_honors.upload, bytes(content), filename, importer_id)


@router.put("/{honor_id}")
def save_honor(
    dep_honors: Annotated[Honors, Depends(service("honors"))], honor_id: str, body: HonorSave
):
    """核对保存条目，拒绝过期版本"""
    return dep_honors.save(body, honor_id)


@router.delete("/{honor_id}")
def delete_honor(
    dep_honors: Annotated[Honors, Depends(service("honors"))],
    honor_id: str,
    version: int = Query(ge=1),
):
    """删除荣誉库记录和原件并保留已保存的简历"""
    return dep_honors.delete(honor_id, version)


@router.post("/{honor_id}/recognize")
def recognize_honor(dep_honors: Annotated[Honors, Depends(service("honors"))], honor_id: str):
    """按当前设置重新识别已有原件"""
    return dep_honors.recognize(honor_id)


@router.post("/{honor_id}/cancel")
def cancel_honor(dep_honors: Annotated[Honors, Depends(service("honors"))], honor_id: str):
    """取消排队或识别中的任务"""
    return dep_honors.cancel(honor_id)


@router.get("/{honor_id}/original")
def original_honor(dep_honors: Annotated[Honors, Depends(service("honors"))], honor_id: str):
    """以附件形式下载原始证书"""
    path, name = dep_honors.file(honor_id)
    return FileResponse(
        path,
        filename=name,
        media_type="application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/{honor_id}/pages/{page}")
def honor_page(dep_honors: Annotated[Honors, Depends(service("honors"))], honor_id: str, page: int):
    """提供由本机解码生成的 PNG 页面，PDF 和图片共用预览"""
    path, _ = dep_honors.file(honor_id, page)
    return FileResponse(path, media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})
