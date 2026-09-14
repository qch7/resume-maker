"""每个应用实例独立持有服务，通过 FastAPI 依赖注入交给路由。"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from resume_maker.core.config import Config
from resume_maker.infrastructure.database import Database
from resume_maker.services.catalog import Catalog
from resume_maker.services.conversations import Conversations
from resume_maker.services.documents import Documents
from resume_maker.services.jobs import Jobs
from resume_maker.services.projects import Projects
from resume_maker.services.resume_previews import ResumePreviews
from resume_maker.services.templates import Templates
from resume_maker.services.workspace import Workspace


@dataclass(frozen=True)
class Services:
    """应用服务容器，禁止用模块全局变量共享用户数据目录。"""

    config: Config
    db: Database
    catalog: Catalog
    jobs: Jobs
    documents: Documents
    workspace: Workspace
    conversations: Conversations
    projects: Projects
    templates: Templates
    resume_previews: ResumePreviews


def get_services(request: Request) -> Services:
    """从当前请求所属应用取得服务，支持多实例隔离与测试替换。"""
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]
