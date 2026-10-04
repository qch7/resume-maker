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
from resume_maker.plugins.discovery import configuration_bundles, selection
from resume_maker.runtime.configuration import compose_configuration, startup_configuration
from resume_maker.runtime.environments import EnvironmentStore
from resume_maker.runtime.graph import PluginError, available_selection
from resume_maker.runtime.host import Host
from resume_maker.runtime.instances import definition_id, expand_instances
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
    packages = PackageStore(
        config.package_root or config.data_dir, set(manifests), records=config.package_records
    )
    external, locations = packages.discover(strict=False)
    manifests.update(external)
    environments = EnvironmentStore(
        config.package_root or config.data_dir, records=config.environment_records
    )
    worker_environments = environments.available(locations)
    instance_specs = (saved or {}).get("instances", [])
    expanded, parsed_specs = expand_instances(manifests, instance_specs, missing_ok=True)
    desired, blocked = set(selected), {}
    if saved and config.profile is None and config.plugins is None:
        selected, blocked = available_selection(
            expanded,
            desired,
            required,
            {
                key: packages.failures[definition_id(parsed_specs, key)]
                for key in desired
                if definition_id(parsed_specs, key) in packages.failures
            },
            {
                key: worker_environments.get(definition_id(parsed_specs, key), {})
                for key in expanded
            },
        )
    layers = startup_configuration(
        saved, config.plugin_config, configuration_bundles(config.profile or "standard")
    )
    if config.plugin_config and any(
        edit["instance"] not in expanded
        for layer in layers
        if layer["name"] != "workspace"
        for edit in layer.get("edits", [])
    ):
        raise PluginError("本次启动配置引用尚未安装的插件实例")
    configuration = compose_configuration(
        expanded,
        layers,
        missing_ok=True,
    )
    configs = configuration["configs"]
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
                "configuration": configuration,
                "environment_store": environments,
                "worker_environments": worker_environments,
            },
            current_generation,
            instance_specs=instance_specs,
        )
        candidate.desired, candidate.blocked = desired, reasons
        candidate.activate()
        return candidate

    host = activate_host(selected, blocked, generation)
    if saved and (
        set(saved.get("effective", saved["selected"])) != host.selected
        or any(
            saved.get("configs", {}).get(key, expanded[key].config) != configs[key]
            for key in host.selected
        )
    ):
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
        if ready := host.bootstrap.get("on_ready"):
            ready()
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
    store.commit(
        desired,
        generation,
        manager.package_lock(),
        retained_configs,
        host.selected,
        instance_specs,
        configuration["layers"],
    )
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
