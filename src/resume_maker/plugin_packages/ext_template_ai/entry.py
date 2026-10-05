"""AI 模板分析的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, routes, task_queue


def activate(context):
    """为模板分析附接统一模型出口和分析实现"""
    from resume_maker.plugin_packages.ext_template_ai.services.templates.analysis_driver import (
        TemplateAnalysis,
    )

    service = dependency(context, "templates")
    context.scope.barriers.append(
        service.attach_analysis(
            dependency(context, "provider"), task_queue(context), TemplateAnalysis()
        )
    )
    context.effect(
        dependency(context, "tasks").attach(
            context.instance_id,
            lambda: [
                {"id": row["id"], "state": row["status"]}
                for row in service.list_tasks()
                if row["status"] == "running"
            ],
            service.cancel,
        )
    )
    routes(context, "resume_maker.plugin_packages.ext_template_ai.routes.templates")
