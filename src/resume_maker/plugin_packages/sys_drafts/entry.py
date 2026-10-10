"""持久草稿的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """发布具有实体版本和恢复代次的持久草稿服务"""
    from resume_maker.plugin_packages.sys_drafts.services.workspace_storage import WorkspaceStorage

    publish(context, "workspace_storage", WorkspaceStorage(dependency(context, "db")))
    routes(context, "resume_maker.plugin_packages.sys_drafts.routes.workspace_storage")
