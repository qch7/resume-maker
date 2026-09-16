"""荣誉条目、受鉴权保护的文件上传与证书预览入口。"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from resume_maker.api.dependencies import ServicesDep
from resume_maker.core.errors import Problem
from resume_maker.domain.honors import HonorSave
from resume_maker.integrations.certificates import MAX_BYTES

router = APIRouter(prefix="/api/honors", tags=["honors"])


@router.get("")
def list_honors(services: ServicesDep):
    """列出持久化荣誉库。"""
    return services.honors.list()


@router.post("")
def create_honor(services: ServicesDep, body: HonorSave):
    """手动添加没有附件的荣誉。"""
    return services.honors.save(body)


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
    request: Request, services: ServicesDep, filename: str = Query(min_length=1, max_length=240)
):
    """流式接收一个原件，先限制实际字节数，再在工作线程解码和入队。"""
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_BYTES:
            raise Problem("单个证书文件不得超过 20 MB。", 413)
        content.extend(chunk)
    return await run_in_threadpool(services.honors.upload, bytes(content), filename)


@router.put("/{honor_id}")
def save_honor(services: ServicesDep, honor_id: str, body: HonorSave):
    """核对保存条目，拒绝过期版本。"""
    return services.honors.save(body, honor_id)


@router.delete("/{honor_id}")
def delete_honor(services: ServicesDep, honor_id: str, version: int = Query(ge=1)):
    """删除库记录和原件，不连带修改已保存的简历。"""
    return services.honors.delete(honor_id, version)


@router.post("/{honor_id}/recognize")
def recognize_honor(services: ServicesDep, honor_id: str):
    """按当前设置重新识别已有原件。"""
    return services.honors.recognize(honor_id)


@router.post("/{honor_id}/cancel")
def cancel_honor(services: ServicesDep, honor_id: str):
    """取消排队或识别中的任务。"""
    return services.honors.cancel(honor_id)


@router.get("/{honor_id}/original")
def original_honor(services: ServicesDep, honor_id: str):
    """下载原始证书，使用附件响应而不执行上传内容。"""
    path, name = services.honors.file(honor_id)
    return FileResponse(
        path,
        filename=name,
        media_type="application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/{honor_id}/pages/{page}")
def honor_page(services: ServicesDep, honor_id: str, page: int):
    """提供由本机解码生成的 PNG 页面，PDF 和图片共用预览。"""
    path, _ = services.honors.file(honor_id, page)
    return FileResponse(path, media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})
