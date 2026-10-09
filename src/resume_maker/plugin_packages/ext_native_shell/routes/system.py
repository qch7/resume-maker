"""健康状态、工作台聚合、关闭和备份的 HTTP 入口"""

from fastapi import APIRouter

from resume_maker.api.schemas import PathPickerInput
from resume_maker.plugin_packages.ext_native_shell.integrations.path_picker import pick_path

router = APIRouter(prefix="/api", tags=["system"])


@router.post("/paths/pick")
def select_path(body: PathPickerInput):
    """在服务器所在的 Windows 桌面打开原生选择窗口，取消时返回空路径"""
    return {"path": pick_path(body.kind, body.initial_path)}
