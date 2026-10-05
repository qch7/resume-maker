"""本机文件交互的注册和生命周期入口"""

from resume_maker.plugins.support import routes


def activate(context):
    """注册明确由用户触发的本机文件选择和来源定位"""
    routes(context, "resume_maker.plugin_packages.ext_native_shell.routes.system")
    routes(context, "resume_maker.plugin_packages.ext_native_shell.routes.projects")
