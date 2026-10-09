"""AI 会话的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes, task_queue


def activate(context):
    """注册 AI 会话和经历分析任务，停用后保留已存历史及草稿"""
    from resume_maker.plugin_packages.ext_ai_conversation.configuration import Settings
    from resume_maker.plugin_packages.ext_ai_conversation.query import conversations as query
    from resume_maker.plugin_packages.ext_ai_conversation.services.conversations import (
        Conversations,
    )
    from resume_maker.plugin_packages.ext_ai_conversation.services.jobs import Jobs

    catalog = dependency(context, "catalog")
    conversations = publish(
        context, "conversations", Conversations(catalog, storage=dependency(context, "db"))
    )
    context.effect(
        catalog.on_project_created(context.instance_id, conversations.initialize_project)
    )
    queue = publish(
        context,
        "jobs",
        Jobs(
            dependency(context, "db"),
            catalog,
            dependency(context, "config").data_dir,
            dependency(context, "provider"),
            conversations=conversations,
            execution_queue=task_queue(context),
            settings=Settings.model_validate(context.config),
            source_service=dependency(context, "sources")
            if "sources" in context.host.services
            else None,
        ),
    )
    context.lifecycle(queue.start, queue.stop)
    context.effect(
        dependency(context, "tasks").attach(
            context.instance_id,
            queue.active_tasks,
            queue.cancel,
        )
    )
    routes(context, "resume_maker.plugin_packages.ext_ai_conversation.routes.conversations")
    routes(context, "resume_maker.plugin_packages.ext_ai_conversation.routes.jobs")
    context.contribute("workspace.queries", "conversations", query)
