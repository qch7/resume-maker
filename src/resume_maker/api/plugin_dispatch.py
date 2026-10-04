"""稳定 API 分派器，插件贡献先构造快照再一次发布"""

from fastapi import FastAPI
from starlette.routing import BaseRoute, Match

from resume_maker import __version__
from resume_maker.api.dependencies import ServiceView
from resume_maker.core.errors import Problem
from resume_maker.runtime.graph import PluginError
from resume_maker.sdk.context import ServiceKey


def snapshot(host, exception_handlers):
    """校验路径及方法唯一后生成不可变路由集合和独立 OpenAPI"""
    app = FastAPI(
        title="Resume Maker",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        exception_handlers=exception_handlers,
    )
    owners, seen = {}, set()
    for contribution in host.collection("http.routes"):
        for route in contribution.value:
            for dependency in route.dependant.dependencies:
                key = getattr(dependency.call, "service_key", None)
                if key is not None:
                    host.instances[contribution.owner].require(key)
            if contribution.owner in host.bootstrap.get(
                "packages", {}
            ) and not route.path.startswith(f"/api/plugins/{contribution.owner}/"):
                raise PluginError("外部插件路由必须位于其公开命名空间")
            for method in route.methods:
                key = (route.path, method)
                if key in seen:
                    raise PluginError(f"HTTP 路由冲突：{method} {route.path}")
                seen.add(key)
            app.router.routes.append(route)
            owners[id(route)] = contribution.owner
    app.state.runtime = host
    app.state.services = ServiceView(host)
    app.state.route_owners = owners
    app.state.contexts = dict(host.instances)
    app.state.generation = host.generation
    return app


class PluginDispatch(BaseRoute):
    """每次请求固定一个注册快照，不修改在途 FastAPI 路由"""

    def __init__(self, app):
        """持有当前完整候选应用，切换时只替换引用"""
        self.current = app

    def matches(self, scope):
        """只接管插件 API，静态首页仍由根宿主管理"""
        return (Match.FULL, {}) if scope["path"].startswith("/api/") else (Match.NONE, {})

    async def handle(self, scope, receive, send):
        """在单次请求期间保留相同应用和服务集合"""
        app = self.current
        scope["root_app"] = scope["app"]
        manager = app.state.runtime.require(ServiceKey("plugins"))
        for route in app.router.routes:
            match, _ = route.matches(scope)
            if match == Match.FULL:
                owner = app.state.route_owners.get(id(route), "sys.http")
                headers = dict(scope.get("headers", []))
                generation = headers.get(b"x-resume-generation")
                if generation is not None:
                    try:
                        generation = int(generation)
                    except ValueError:
                        raise Problem("插件代次格式无效。", 422) from None
                flush = owner == "sys.drafts" or scope["path"].endswith("/draft")
                with manager.request(
                    owner,
                    write=scope["method"] not in {"GET", "HEAD", "OPTIONS"},
                    flush=flush,
                    generation=generation,
                    route_generation=app.state.generation,
                ):
                    return await app(scope, receive, send)
        await app(scope, receive, send)

    def url_path_for(self, name, /, **path_params):
        """由当前路由快照解析具名路径"""
        return self.current.url_path_for(name, **path_params)
