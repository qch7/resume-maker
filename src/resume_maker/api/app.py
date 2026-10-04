"""启动器只装配运行时和 HTTP 外壳，业务入口由清单发现"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from resume_maker import __version__
from resume_maker.api.activity import ActivityMiddleware
from resume_maker.api.dependencies import ServiceView
from resume_maker.api.middleware import configure_middleware
from resume_maker.api.plugin_dispatch import PluginDispatch, snapshot
from resume_maker.api.static import mount_frontend
from resume_maker.core.config import Config
from resume_maker.plugins.discovery import selection
from resume_maker.runtime.configuration import configurations
from resume_maker.runtime.environments import EnvironmentStore
from resume_maker.runtime.graph import available_selection
from resume_maker.runtime.host import Host
from resume_maker.runtime.packages import PackageStore
from resume_maker.runtime.state import StateStore
from resume_maker.sdk.context import ServiceKey
from resume_maker.sdk.model import Provider


def create_app(config: Config | None = None, provider: Provider | None = None) -> FastAPI:
    """解析完整组合后激活插件，未选择的模块不会被入口集中导入"""
    config = config or Config()
    config.prepare()
    store = StateStore(config.data_dir)
    saved = store.read()
    overrides = config.plugins
    if saved and config.profile is None and overrides is None:
        overrides = tuple(saved["selected"])
    manifests, selected, required = selection(config.profile or "standard", overrides)
    packages = PackageStore(config.data_dir, set(manifests))
    external, locations = packages.discover(strict=False)
    manifests.update(external)
    environments = EnvironmentStore(config.data_dir)
    worker_environments = environments.available(locations)
    desired, blocked = set(selected), {}
    if saved and config.profile is None and config.plugins is None:
        selected, blocked = available_selection(
            manifests, desired, required, packages.failures, worker_environments
        )
    configs = configurations(
        manifests,
        {key: value for key, value in (saved or {}).get("configs", {}).items() if key in manifests},
    )
    generation = saved["generation"] if saved else 1

    def activate_host(selection, reasons, current_generation):
        """只在全部注册验证完成后返回宿主，实际能力变化重新绑定统一代次"""
        candidate = Host(
            manifests,
            selection,
            required,
            {
                "config": config,
                "provider": provider,
                "state_store": store,
                "packages": locations,
                "package_store": packages,
                "configs": configs,
                "environment_store": environments,
                "worker_environments": worker_environments,
            },
            current_generation,
        )
        candidate.desired, candidate.blocked = desired, reasons
        candidate.activate()
        return candidate

    host = activate_host(selected, blocked, generation)
    if saved and set(saved.get("effective", saved["selected"])) != host.selected:
        selected, blocked = set(host.selected), dict(host.blocked)
        host.close()
        generation += 1
        host = activate_host(selected, blocked, generation)
    log = host.require(ServiceKey("activity"))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        """后台工作遵守插件拓扑启动和逆依赖关闭"""
        log.write("system", "startup", "本机服务启动", {"instance_id": config.instance_id})
        host.start()
        try:
            yield
        finally:
            host.close()
            log.write("system", "shutdown", "本机服务停止")

    app = FastAPI(title="Resume Maker", version=__version__, lifespan=lifespan)
    app.state.runtime = host
    app.state.services = ServiceView(host)
    configure_middleware(app, config)
    app.add_middleware(ActivityMiddleware, log=log)
    dispatch = PluginDispatch(snapshot(host, app.exception_handlers))
    manager = host.require(ServiceKey("plugins"))

    def publish_routes():
        """完整候选路由通过验证后原子替换，已有请求仍使用旧快照"""
        dispatch.current = snapshot(host, app.exception_handlers)

    manager.publish_routes = publish_routes
    retained_configs = {**(saved or {}).get("configs", {}), **configs}
    store.commit(desired, generation, manager.package_lock(), retained_configs, host.selected)
    app.router.routes.append(dispatch)
    app.state.dispatch = dispatch

    def openapi():
        """插件 API 和根静态入口共享完整 HTTP 契约"""
        return get_openapi(
            title="Resume Maker",
            version=__version__,
            routes=[
                *dispatch.current.router.routes,
                *(route for route in app.router.routes if route is not dispatch),
            ],
        )

    app.openapi = openapi
    mount_frontend(app, config)
    return app
