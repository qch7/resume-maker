"""工作台的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """建立工作台查询扩展点，系统页面只读取系统能力"""
    from resume_maker.plugin_packages.sys_workbench.services.workspace import Workspace

    publish(
        context,
        "workspace",
        Workspace(
            dependency(context, "db"),
            readers=[
                dependency(context, name).workspace_state
                for name in ("catalog", "resume", "settings")
            ],
            contributors=lambda: context.host.collection("workspace.queries"),
        ),
    )
    routes(context, "resume_maker.plugin_packages.sys_workbench.routes.system")
