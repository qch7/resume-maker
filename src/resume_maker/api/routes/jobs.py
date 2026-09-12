"""任务取消、事件流及建议处理的 HTTP 入口。"""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from resume_maker.api.dependencies import ServicesDep
from resume_maker.core.errors import need
from resume_maker.infrastructure.database import dump

router = APIRouter(prefix="/api", tags=["jobs"])


@router.post("/jobs/{job_id}/cancel")
def cancel(services: ServicesDep, job_id: str):
    """同时更新持久状态和进程取消信号，阻止任务结果继续发布。"""
    services.jobs.cancel(job_id)
    return {"ok": True}


@router.get("/jobs/{job_id}/events")
async def events(services: ServicesDep, job_id: str, request: Request, after: int = 0):
    """校验任务存在后打开事件流，支持从上次游标继续读取。"""
    need(services.db.one("SELECT id FROM jobs WHERE id=?", (job_id,)))

    async def stream():
        """按递增事件编号重放进度，发送心跳并在任务结束或客户端断开时退出。"""
        cursor = after
        while not await request.is_disconnected():
            rows = services.db.all(
                "SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id", (job_id, cursor)
            )
            for row in rows:
                cursor = row["id"]
                yield f"id: {cursor}\ndata: {dump(row)}\n\n"
            job = services.db.one("SELECT status FROM jobs WHERE id=?", (job_id,))
            if job["status"] not in {"queued", "running"}:
                yield f"event: done\ndata: {dump(job)}\n\n"
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/proposals/{proposal_id}/adopt")
def adopt(services: ServicesDep, proposal_id: str):
    """检查建议原文与当前内容一致后写入草稿，避免覆盖后续人工编辑。"""
    return services.catalog.adopt(proposal_id)


@router.post("/proposals/{proposal_id}/reject")
def reject(services: ServicesDep, proposal_id: str):
    """将尚未处理的 AI 建议标记为拒绝，不修改经历内容。"""
    with services.db.transaction() as conn:
        conn.execute(
            "UPDATE proposals SET status='rejected' WHERE id=? AND status='pending'",
            (proposal_id,),
        )
    return {"ok": True}
