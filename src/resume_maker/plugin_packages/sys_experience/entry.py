"""经历与版本的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """发布经历、固定修订及草稿事务，默认不创建 AI 会话"""
    from resume_maker.plugin_packages.sys_experience.services.catalog import Catalog
    from resume_maker.plugin_packages.sys_experience.services.projects import Projects

    catalog = publish(
        context,
        "catalog",
        Catalog(dependency(context, "db"), assets=dependency(context, "assets")),
    )
    publish(context, "projects", Projects(catalog))
    routes(context, "resume_maker.plugin_packages.sys_experience.routes.projects")
