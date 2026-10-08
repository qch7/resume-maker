"""模板库的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """注册模板组织、回收站和数据清理生命周期"""
    from resume_maker.plugin_packages.ext_template_library.configuration import Settings
    from resume_maker.plugin_packages.ext_template_library.query import templates as query
    from resume_maker.plugin_packages.ext_template_library.services.templates.library import (
        TemplateLibrary,
    )

    service = publish(
        context,
        "template_library",
        TemplateLibrary(
            dependency(context, "resume"),
            dependency(context, "config").data_dir,
            dependency(context, "templates"),
            dependency(context, "resume_previews"),
            records=dependency(context, "template.records"),
            storage=dependency(context, "db"),
            assets=dependency(context, "assets"),
            registry=dependency(context, "document.registry"),
            settings=Settings.model_validate(context.config),
        ),
    )
    context.lifecycle(service.start, service.stop)
    routes(context, "resume_maker.plugin_packages.ext_template_library.routes.templates")
    context.contribute("workspace.queries", "templates", query)
