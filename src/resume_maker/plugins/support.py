"""内置插件共用的注册操作，不持有业务能力清单"""

from importlib import import_module

from resume_maker.runtime.host import PluginContext
from resume_maker.sdk.context import ServiceKey


def dependency(context: PluginContext, name: str):
    """按插件清单取得单个公开服务"""
    return context.require(ServiceKey(name))


def publish(context: PluginContext, name: str, service, *, observed: bool = True):
    """登记业务服务并在日志能力存在时统一挂接观测"""
    if observed and "activity" in context.manifest.requires.get("host", {}):
        from resume_maker.infrastructure.observability import instrument_service

        instrument_service(
            service,
            dependency(context, "activity"),
            name,
            background=("_run", "_analyze", "_recognize"),
        )
    context.provide(ServiceKey(name), service)
    return service


def routes(
    context: PluginContext,
    module: str,
    *,
    only: set[str] | None = None,
    exclude: set[str] | None = None,
):
    """登记当前插件私有目录内拥有的路由"""
    package = "resume_maker.plugin_packages." + context.manifest.id.replace(".", "_").replace(
        "-", "_"
    )
    if not module.startswith(package + ".routes."):
        raise ValueError("路由必须位于当前插件包内。")
    router = import_module(module).router
    selected = tuple(
        route
        for route in router.routes
        if (only is None or route.name in only) and (exclude is None or route.name not in exclude)
    )
    name = module.rsplit(".", 1)[-1]
    context.contribute("http.routes", f"{context.instance_id}/{name}", selected)


def task_queue(context):
    """固定任务所有者、插件版本及提供方绑定，执行租约由系统持有"""
    return dependency(context, "tasks").scope(
        context.instance_id,
        context.generation,
        {
            name: {"id": owner, "version": context.host.manifests[owner].version}
            for name, owner in context.host.resolution.providers.items()
        },
        context.manifest.version,
    )
