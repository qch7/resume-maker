"""应用组装入口：配置、服务生命周期、路由和静态资源"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from resume_maker import __version__
from resume_maker.api.activity import ActivityMiddleware
from resume_maker.api.dependencies import Services
from resume_maker.api.middleware import configure_middleware
from resume_maker.api.routes import (
    activity,
    conversations,
    honors,
    jobs,
    privacy,
    projects,
    resumes,
    settings,
    system,
    templates,
    workspace_storage,
)
from resume_maker.api.static import mount_frontend
from resume_maker.core.config import Config
from resume_maker.infrastructure.activity import ActivityLog
from resume_maker.infrastructure.database import Database
from resume_maker.infrastructure.observability import install_logging, instrument_service
from resume_maker.integrations.privacy_store import PrivacyStore
from resume_maker.integrations.providers.base import Provider
from resume_maker.integrations.providers.codex import CodexProvider
from resume_maker.services.catalog import Catalog
from resume_maker.services.conversations import Conversations
from resume_maker.services.documents import Documents
from resume_maker.services.honors import Honors
from resume_maker.services.jobs import Jobs
from resume_maker.services.privacy import Privacy
from resume_maker.services.projects import Projects
from resume_maker.services.resume_previews import ResumePreviews
from resume_maker.services.settings import Settings
from resume_maker.services.templates.library import TemplateLibrary
from resume_maker.services.templates.tasks import Templates
from resume_maker.services.workspace import Workspace
from resume_maker.services.workspace_storage import WorkspaceStorage


def create_app(config: Config | None = None, provider: Provider | None = None) -> FastAPI:
    """按配置组装独立应用，后台任务由应用生命周期启动"""
    config = config or Config()
    config.prepare()
    db = Database(config.data_dir / "resume.db")
    db.activity = ActivityLog(config.data_dir / "logs" / "activity.sqlite", secrets=(config.token,))
    db.activity.import_history(db)
    install_logging()
    privacy_store = PrivacyStore(db)
    provider = provider if provider is not None else CodexProvider(privacy=privacy_store)
    catalog = Catalog(db)
    queue = Jobs(db, catalog, config.data_dir, provider)
    template_service = Templates(catalog, config.data_dir, provider)
    preview_service = ResumePreviews(catalog, config.data_dir)
    services = Services(
        config=config,
        db=db,
        catalog=catalog,
        jobs=queue,
        honors=Honors(db, config.data_dir, provider),
        settings=Settings(db, config.data_dir, provider),
        privacy=Privacy(db, privacy_store),
        documents=Documents(catalog, config.data_dir),
        resume_previews=preview_service,
        templates=template_service,
        template_library=TemplateLibrary(
            catalog, config.data_dir, template_service, preview_service
        ),
        projects=Projects(catalog),
        conversations=Conversations(catalog),
        workspace=Workspace(catalog),
        workspace_storage=WorkspaceStorage(db),
    )

    for name in (
        "catalog",
        "jobs",
        "honors",
        "documents",
        "resume_previews",
        "templates",
        "template_library",
        "projects",
        "conversations",
        "workspace",
        "settings",
        "privacy",
        "workspace_storage",
    ):
        instrument_service(
            getattr(services, name),
            db.activity,
            name,
            background=("_run", "_analyze", "_recognize"),
        )
    instrument_service(catalog.history, db.activity, "history")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        """随服务器启动队列并在正常关闭或异常退出时回收任务进程"""
        db.activity.write("system", "startup", "本机服务启动", {"instance_id": config.instance_id})
        queue.start()
        services.honors.start()
        services.template_library.start()
        try:
            yield
        finally:
            services.template_library.stop()
            services.honors.stop()
            services.templates.stop()
            services.resume_previews.stop()
            queue.stop()
            db.activity.write("system", "shutdown", "本机服务停止")

    app = FastAPI(title="Resume Maker", version=__version__, lifespan=lifespan)
    app.state.services = services
    configure_middleware(app, config)
    app.add_middleware(ActivityMiddleware, log=db.activity)
    for module in (
        activity,
        system,
        projects,
        conversations,
        jobs,
        resumes,
        templates,
        settings,
        honors,
        privacy,
        workspace_storage,
    ):
        app.include_router(module.router)
    mount_frontend(app, config)
    return app
