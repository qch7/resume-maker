"""简历编排的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """发布固定引用的简历编辑和历史接口"""
    from resume_maker.plugin_packages.sys_resume.services.resume_sources import ResumeSources
    from resume_maker.plugin_packages.sys_resume.services.resumes import Resumes

    sources = ResumeSources(dependency(context, "db"), context.host.collection)
    service = publish(
        context,
        "resume",
        Resumes(
            dependency(context, "catalog"),
            storage=dependency(context, "db"),
            sources=sources,
            assets=dependency(context, "assets"),
        ),
    )
    context.before_deactivate.append(service.preserve_sources)
    context.health(sources.entries)
    routes(context, "resume_maker.plugin_packages.sys_resume.routes.resumes")
