"""本机 HTTP的注册和生命周期入口"""

from resume_maker.plugins.support import publish, routes


def activate(context):
    """提供本机 HTTP 宿主入口和公共健康诊断"""
    publish(context, "http", context.host, observed=False)
    routes(context, "resume_maker.plugin_packages.sys_http.routes.system")
