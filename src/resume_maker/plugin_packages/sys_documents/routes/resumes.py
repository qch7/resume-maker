"""固定版本简历组合和导出下载的 HTTP 入口"""

import threading
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from resume_maker.api.dependencies import service
from resume_maker.api.resources import AssetResponse, LeasedFileResponse
from resume_maker.api.schemas import ResumePreviewInput
from resume_maker.core.errors import Problem, need
from resume_maker.infrastructure.assets import Assets
from resume_maker.infrastructure.database import Database
from resume_maker.sdk.model import Cancelled
from resume_maker.sdk.records import dump
from resume_maker.sdk.services import Documents, ResumePreviews

router = APIRouter(prefix="/api", tags=["resumes"])


@router.post("/resume-previews")
async def preview_resume(
    dep_resume_previews: Annotated[ResumePreviews, Depends(service("resume_previews"))],
    body: ResumePreviewInput,
    request: Request,
    engine_id: str | None = None,
    renderer_id: str | None = None,
):
    """用当前模板为未保存资料生成临时预览"""
    cancelled = threading.Event()
    result, failure, monitor_failure = None, None, None
    finished = anyio.Event()
    with dep_resume_previews.request_work(cancelled) as work:

        async def watch_request(waiting):
            """过期及断开取消池外等待，框架取消也立即通知真实生成器"""
            nonlocal monitor_failure
            try:
                while not finished.is_set():
                    work.check()
                    disconnected = await request.is_disconnected()
                    if finished.is_set():
                        return
                    if disconnected:
                        raise Cancelled("预览请求已断开。")
                    await anyio.sleep(0.05)
            except Exception as exc:
                if not finished.is_set():
                    monitor_failure = exc
                    waiting.cancel()
            finally:
                cancelled.set()

        async def render(*, task_status=anyio.TASK_STATUS_IGNORED):
            """子任务持有实际线程直到清理结束，父请求取消不会提前释放容量"""
            nonlocal result, failure
            with anyio.CancelScope() as waiting:
                task_status.started(waiting)
                try:
                    result = await run_in_threadpool(
                        dep_resume_previews.render,
                        body.template_id,
                        body.document.model_dump(),
                        [item.model_dump() for item in body.items],
                        engine_id=engine_id,
                        renderer_id=renderer_id,
                        cancelled=cancelled,
                        force=request.headers.get("x-resume-preview-force") == "1",
                    )
                except Exception as exc:
                    failure = exc
                finally:
                    finished.set()
                    cancelled.set()

        async with anyio.create_task_group() as group:
            waiting = await group.start(render)
            group.start_soon(watch_request, waiting)
            await finished.wait()
            group.cancel_scope.cancel()
        # 内层清理屏障结束后重新传播父请求的取消，阻止返回迟到结果
        await anyio.lowlevel.checkpoint()
        if monitor_failure is not None:
            raise monitor_failure
        if failure is not None:
            raise failure
        if result is None:
            raise Cancelled("预览请求已取消。")
        return result


@router.get("/resume-previews/{preview_id}/{file_name}")
def preview_file(
    dep_resume_previews: Annotated[ResumePreviews, Depends(service("resume_previews"))],
    preview_id: str,
    file_name: str,
):
    """鉴权后返回本实例已生成的 Word 预览"""
    return LeasedFileResponse(lambda: dep_resume_previews.lease(preview_id, file_name), file_name)


@router.post("/resumes/{resume_id}/exports")
def export(
    dep_documents: Annotated[Documents, Depends(service("documents"))],
    resume_id: str,
    version: Annotated[int, Query(ge=0)],
    engine_id: str | None = None,
    renderer_id: str | None = None,
):
    """读取固定版本组合，生成完整简历 Word、预览和追溯清单"""
    return dep_documents.export(
        resume_id, expected_version=version, engine_id=engine_id, renderer_id=renderer_id
    )


@router.get("/document-engines")
def document_engines(dep_documents: Annotated[Documents, Depends(service("documents"))]):
    """向插件客户端提供可选引擎，不按加载顺序替换默认实现"""
    return dep_documents.engines()


@router.get("/document-importers")
def document_importers(
    dep_documents: Annotated[Documents, Depends(service("documents"))], purpose: str = "template"
):
    """公开已启用的格式和处理器，上传时仍须探测实际内容"""
    return dep_documents.importers(purpose)


@router.get("/resumes/{resume_id}/exports")
def export_history(dep_db: Annotated[Database, Depends(service("db"))], resume_id: str):
    """列出指定简历的历史导出，让重新打开页面时可恢复上次预览"""
    return dep_db.all(
        "SELECT * FROM exports WHERE resume_id=? ORDER BY created_at DESC", (resume_id,)
    )


@router.get("/exports/{export_id}/{file_name}")
def export_file(
    dep_assets: Annotated[Assets, Depends(service("assets"))],
    dep_db: Annotated[Database, Depends(service("db"))],
    export_id: str,
    file_name: str,
):
    """仅允许下载本次导出登记的 DOCX、PDF、清单或有效页码图片"""
    record = need(dep_db.one("SELECT * FROM exports WHERE id=?", (export_id,)))
    allowed = {"resume.docx", "resume.pdf", "manifest.json"}
    allowed.update(f"page-{i}.png" for i in range(1, (record["pages"] or 0) + 1))
    if file_name not in allowed:
        raise Problem("文件不存在。", 404)
    if file_name == "manifest.json":
        return Response(
            dump(record["manifest"]),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="manifest.json"'},
        )
    asset_id = record["manifest"]["assets"].get(file_name)
    if not asset_id:
        raise Problem("该文件尚未生成。", 404)
    return AssetResponse(dep_assets, asset_id, file_name)
