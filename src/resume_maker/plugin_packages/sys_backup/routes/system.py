"""健康状态、工作台聚合、关闭和备份的 HTTP 入口"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from resume_maker.api.dependencies import service
from resume_maker.core.config import Config
from resume_maker.infrastructure.database import Database, now
from resume_maker.infrastructure.storage import create_backup

router = APIRouter(prefix="/api", tags=["system"])


@router.post("/backups")
def backup(
    dep_config: Annotated[Config, Depends(service("config"))],
    dep_db: Annotated[Database, Depends(service("db"))],
):
    """生成一致性备份 ZIP并作为带日期文件名的下载返回"""
    output = create_backup(dep_db, dep_config.data_dir)
    return FileResponse(output, filename=f"resume-maker-{now()[:10]}.zip")
