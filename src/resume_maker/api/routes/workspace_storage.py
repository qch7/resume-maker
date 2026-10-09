"""本机编辑草稿及偏好的恢复和并发保存入口"""

from fastapi import APIRouter
from pydantic import Field

from resume_maker.api.dependencies import ServicesDep
from resume_maker.domain.models import Model

router = APIRouter(prefix="/api/workspace-storage", tags=["workspace"])


class WorkspaceValueInput(Model):
    """空值表示删除，版本仍保留以拒绝旧窗口写入"""

    value: str | None = Field(default=None, max_length=8_000_000)
    version: int = Field(ge=0)


@router.get("")
def workspace_values(services: ServicesDep):
    """恢复当前数据目录的草稿及界面偏好"""
    return services.workspace_storage.state()


@router.put("/{key}")
def save_workspace_value(services: ServicesDep, key: str, body: WorkspaceValueInput):
    """自动保留输入，不发布简历、荣誉或模板的正式版本"""
    return services.workspace_storage.save(key, body.value, body.version)
