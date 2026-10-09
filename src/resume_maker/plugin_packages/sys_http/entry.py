"""本机 HTTP的注册和生命周期入口"""

from resume_maker.plugins.support import publish, routes


def activate(context):
    """提供本机 HTTP 宿主入口和公共健康诊断"""
    publish(context, "http", context.host, observed=False)
    from resume_maker.infrastructure.plugin_http import PluginHTTP

    client = publish(context, "http.client", PluginHTTP(), observed=False)
    context.lifecycle(client.start, client.close)
    routes(context, "resume_maker.plugin_packages.sys_http.routes.system")
