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
    """登记插件拥有的路由，混合模块只发布显式归属的端点"""
    router = import_module(f"resume_maker.api.routes.{module}").router
    selected = tuple(
        route
        for route in router.routes
        if (only is None or route.name in only) and (exclude is None or route.name not in exclude)
    )
    context.contribute("http.routes", f"{context.instance_id}/{module}", selected)
