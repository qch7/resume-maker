"""健康状态、工作台聚合、关闭和备份的 HTTP 入口"""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import Field
from starlette.background import BackgroundTask

from resume_maker.api.dependencies import service
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.infrastructure.backup_history import backup_path, list_backups, protected_backups
from resume_maker.infrastructure.database import Database, now
from resume_maker.infrastructure.storage import create_backup
from resume_maker.runtime.backup_restore import plan_restore, read_restore
from resume_maker.runtime.manager import PluginManager
from resume_maker.sdk.manifest import Contract

router = APIRouter(prefix="/api", tags=["system"])


class RestoreInput(Contract):
    """恢复请求绑定当前窗口的插件代次"""

    generation: int = Field(ge=1)


def archive_response(path, filename):
    """下载在响应前打开文件，删除竞争不会使已开始的下载丢失"""
    source = path.open("rb")

    def chunks():
        """分块发送并在传输结束时关闭文件句柄"""
        try:
            while chunk := source.read(1024 * 1024):
                yield chunk
        finally:
            source.close()

    return StreamingResponse(
        chunks(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename)},
        background=BackgroundTask(source.close),
    )


@router.get("/backups")
def history(
    dep_config: Annotated[Config, Depends(service("config"))],
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))],
):
    """按创建时间倒序返回备份来源、大小及正在使用的恢复点"""
    with dep_plugins.lock:
        protected = protected_backups(dep_plugins)
        return {
            "items": [
                {**item, "protected": item["id"] in protected}
                for item in list_backups(dep_config.data_dir)
            ],
            "can_restore": bool(dep_plugins.host.bootstrap.get("request_restart")),
            "restore": read_restore(dep_config.data_dir),
            "pending_restore": next(
                (
                    dep_plugins.progress(item["id"])
                    for item in dep_plugins.plans.values()
                    if item.get("restore_backup") and item["state"] in {"planned", "preparing"}
                ),
                None,
            ),
        }


@router.post("/backups")
def backup(
    dep_config: Annotated[Config, Depends(service("config"))],
    dep_db: Annotated[Database, Depends(service("db"))],
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))],
):
    """生成一致性备份 ZIP并作为带日期文件名的下载返回"""
    with dep_plugins.lock:
        if dep_plugins.pending_plan or dep_plugins.maintenance:
            raise Problem("资料正在变更，请完成后再创建备份。", 409)
    output = create_backup(dep_db, dep_config.data_dir, kind="manual", reason="manual")
    with dep_plugins.lock:
        return archive_response(output, f"resume-maker-{now()[:10]}.zip")


@router.get("/backups/{identifier}/download")
def download_backup(
    identifier: str,
    dep_config: Annotated[Config, Depends(service("config"))],
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))],
):
    """下载选定历史备份，不额外创建新备份"""
    with dep_plugins.lock:
        return archive_response(backup_path(dep_config.data_dir, identifier), identifier)


@router.delete("/backups/{identifier}")
def delete_backup(
    identifier: str,
    dep_config: Annotated[Config, Depends(service("config"))],
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))],
):
    """删除确认的单份 ZIP，活动恢复点及目录外文件不可删除"""
    with dep_plugins.lock:
        if identifier in protected_backups(dep_plugins):
            raise Problem("此备份正在用于恢复或升级，暂时不能删除。", 409)
        path = backup_path(dep_config.data_dir, identifier)
        try:
            path.unlink()
        except OSError as exc:
            raise Problem("备份正被占用或无法删除，请稍后重试。", 409) from exc
        return {"ok": True}


@router.post("/backups/{identifier}/restore-plan")
def prepare_restore(
    identifier: str,
    body: RestoreInput,
    dep_plugins: Annotated[PluginManager, Depends(service("plugins"))],
):
    """建立具体备份的恢复计划，复用全部窗口保存确认协议"""
    return plan_restore(dep_plugins, identifier, body.generation)
