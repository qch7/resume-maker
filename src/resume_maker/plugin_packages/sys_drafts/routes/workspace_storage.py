"""本机编辑草稿及偏好的恢复和并发保存入口"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import Field

from resume_maker.api.dependencies import service
from resume_maker.domain.models import Model
from resume_maker.sdk.services import WorkspaceStorage

router = APIRouter(prefix="/api/workspace-storage", tags=["workspace"])


class WorkspaceValueInput(Model):
    """空值表示删除，版本仍保留以拒绝旧窗口写入"""

    value: str | None = Field(default=None, max_length=8_000_000)
    version: int = Field(ge=0)


@router.get("")
def workspace_values(
    dep_workspace_storage: Annotated[WorkspaceStorage, Depends(service("workspace_storage"))],
):
    """恢复当前数据目录的草稿及界面偏好"""
    return dep_workspace_storage.state()


@router.put("/{key}")
def save_workspace_value(
    dep_workspace_storage: Annotated[WorkspaceStorage, Depends(service("workspace_storage"))],
    key: str,
    body: WorkspaceValueInput,
):
    """自动保留输入，不发布简历、荣誉或模板的正式版本"""
    return dep_workspace_storage.save(key, body.value, body.version)
