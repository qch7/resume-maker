"""健康状态、工作台聚合、关闭与备份的 HTTP 入口。"""

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from resume_maker import __version__
from resume_maker.api.dependencies import ServicesDep
from resume_maker.api.schemas import PathPickerInput
from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import now
from resume_maker.infrastructure.storage import create_backup
from resume_maker.integrations.path_picker import pick_path

router = APIRouter(prefix="/api", tags=["system"])


@router.post("/paths/pick")
def select_path(body: PathPickerInput):
    """在服务器所在的 Windows 桌面打开原生选择窗口，取消时返回空路径。"""
    return {"path": pick_path(body.kind, body.initial_path)}


@router.get("/health")
def health(
    services: ServicesDep,
):
    """返回本机服务状态和实例标识，供启动、停止脚本核验身份。"""
    return {"status": "ok", "version": __version__, "instance_id": services.config.instance_id}


@router.post("/shutdown")
def shutdown(
    request: Request,
):
    """调用当前服务器的正常关闭入口，使后台任务有机会回收资源。"""
    callback = getattr(request.app.state, "stop_server", None)
    if callback is None:
        raise Problem("请从运行服务器的终端关闭应用。")
    callback()
    return {"ok": True}


@router.get("/state")
def state(
    services: ServicesDep,
):
    """聚合项目活动时间、会话、简历、模板及最近任务，供工作台轮询。"""
    return services.workspace.state()


@router.post("/backups")
def backup(
    services: ServicesDep,
):
    """生成一致性备份 ZIP，并作为带日期文件名的下载返回。"""
    output = create_backup(services.db, services.config.data_dir)
    return FileResponse(output, filename=f"resume-maker-{now()[:10]}.zip")
