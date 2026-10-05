"""任务取消、事件流及建议处理的 HTTP 入口"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from resume_maker.api.dependencies import service
from resume_maker.core.errors import need
from resume_maker.infrastructure.database import Database, dump
from resume_maker.sdk.services import Conversations, Jobs

router = APIRouter(prefix="/api", tags=["jobs"])


@router.post("/jobs/{job_id}/cancel")
def cancel(dep_jobs: Annotated[Jobs, Depends(service("jobs"))], job_id: str):
    """同时更新持久状态和进程取消信号，阻止任务结果继续发布"""
    dep_jobs.cancel(job_id)
    return {"ok": True}


@router.get("/jobs/{job_id}/events")
async def events(
    dep_db: Annotated[Database, Depends(service("db"))],
    job_id: str,
    request: Request,
    after: int = 0,
):
    """校验任务存在后打开事件流，支持从上次游标继续读取"""
    need(dep_db.one("SELECT id FROM jobs WHERE id=?", (job_id,)))

    async def stream():
        """按递增事件编号重放进度，发送心跳并在任务结束或客户端断开时退出"""
        cursor = after
        while not await request.is_disconnected():
            rows = dep_db.all(
                "SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id", (job_id, cursor)
            )
            for row in rows:
                cursor = row["id"]
                yield f"id: {cursor}\ndata: {dump(row)}\n\n"
            job = dep_db.one("SELECT status FROM jobs WHERE id=?", (job_id,))
            if job["status"] not in {"queued", "running"}:
                yield f"event: done\ndata: {dump(job)}\n\n"
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/proposals/{proposal_id}/adopt")
def adopt(
    dep_conversations: Annotated[Conversations, Depends(service("conversations"))], proposal_id: str
):
    """检查建议原文和当前内容一致后写入草稿以免覆盖后续人工编辑"""
    return dep_conversations.adopt(proposal_id)


@router.post("/proposals/{proposal_id}/reject")
def reject(dep_db: Annotated[Database, Depends(service("db"))], proposal_id: str):
    """拒绝尚未处理的 AI 建议"""
    with dep_db.transaction() as conn:
        conn.execute(
            "UPDATE proposals SET status='rejected' WHERE id=? AND status='pending'",
            (proposal_id,),
        )
    return {"ok": True}
