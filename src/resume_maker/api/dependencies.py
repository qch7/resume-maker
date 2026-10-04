"""按路由所有者声明注入依赖，不再集中构造业务服务"""

from fastapi import Request

from resume_maker.runtime.graph import PluginError
from resume_maker.sdk.context import ServiceKey


class ServiceView:
    """只读服务投影，业务请求只能取得所属插件已声明的能力"""

    def __init__(self, host, owner=None):
        """宿主诊断可遍历能力，请求视图则按插件清单收窄"""
        self.host, self.owner = host, owner

    def __getattr__(self, name):
        """保留现有路由属性语法，实际依赖取自插件作用域"""
        if self.owner:
            return self.host.instances[self.owner].require(ServiceKey(name))
        try:
            return self.host.require(ServiceKey(name))
        except PluginError as exc:
            raise AttributeError(name) from exc


def service(name: str):
    """路由逐项声明依赖，解析器按当前所有者清单校验授权"""

    def resolve(request: Request):
        """在请求租约内读取同代次的公开能力，参数不暴露万能容器"""
        route = request.scope["route"]
        owner = request.app.state.route_owners[id(route)]
        return request.app.state.contexts[owner].require(ServiceKey(name))

    resolve.service_key = ServiceKey(name)
    return resolve
