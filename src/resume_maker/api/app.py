"""应用组装入口：配置、服务生命周期、路由和静态资源。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from resume_maker import __version__
from resume_maker.api.dependencies import Services
from resume_maker.api.middleware import configure_middleware
from resume_maker.api.routes import (
    conversations,
    jobs,
    projects,
    resumes,
    settings,
    system,
    templates,
)
from resume_maker.api.static import mount_frontend
from resume_maker.core.config import Config
from resume_maker.infrastructure.database import Database
from resume_maker.integrations.providers.base import Provider
from resume_maker.services.catalog import Catalog
from resume_maker.services.conversations import Conversations
from resume_maker.services.documents import Documents
from resume_maker.services.jobs import Jobs
from resume_maker.services.projects import Projects
from resume_maker.services.workspace import Workspace


def create_app(config: Config | None = None, provider: Provider | None = None) -> FastAPI:
    """创建独立应用；可注入配置和 Provider，不在模块导入时启动后台任务。"""
    config = config or Config()
    config.prepare()
    db = Database(config.data_dir / "resume.db")
    catalog = Catalog(db)
    catalog.ensure_subprojects()
    queue = Jobs(db, catalog, config.data_dir, provider)
    services = Services(
        config=config,
        db=db,
        catalog=catalog,
        jobs=queue,
        documents=Documents(catalog, config.data_dir),
        projects=Projects(catalog),
        conversations=Conversations(catalog),
        workspace=Workspace(catalog),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        """随服务器启动队列，并在正常关闭或异常退出时回收任务进程。"""
        queue.start()
        try:
            yield
        finally:
            queue.stop()

    app = FastAPI(title="Resume Maker", version=__version__, lifespan=lifespan)
    app.state.services = services
    configure_middleware(app, config)
    for module in (system, projects, conversations, jobs, resumes, templates, settings):
        app.include_router(module.router)
    mount_frontend(app, config)
    return app
