"""源码资料的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """注册只读来源扫描和绑定接口，手工项目不依赖来源能力"""
    from resume_maker.plugin_packages.ext_source_code.configuration import Settings
    from resume_maker.plugin_packages.ext_source_code.integrations.source_service import (
        SourceService,
    )

    publish(
        context,
        "sources",
        SourceService(
            dependency(context, "catalog"),
            dependency(context, "config").data_dir,
            assets=dependency(context, "assets"),
            policy=Settings.model_validate(context.config),
        ),
        observed=False,
    )
    routes(context, "resume_maker.plugin_packages.ext_source_code.routes.projects")
