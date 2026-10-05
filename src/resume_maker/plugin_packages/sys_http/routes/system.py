"""健康状态、工作台聚合、关闭和备份的 HTTP 入口"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from resume_maker import __version__
from resume_maker.api.dependencies import service
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(
    dep_config: Annotated[Config, Depends(service("config"))],
):
    """返回本机服务状态和实例标识，供启动、停止脚本核验身份"""
    return {"status": "ok", "version": __version__, "instance_id": dep_config.instance_id}


@router.post("/shutdown")
def shutdown(
    request: Request,
):
    """调用当前服务器的正常关闭入口，使后台任务有机会回收资源"""
    callback = getattr(request.scope.get("root_app", request.app).state, "stop_server", None)
    if callback is None:
        raise Problem("请从运行服务器的终端关闭应用。")
    callback()
    return {"ok": True}
