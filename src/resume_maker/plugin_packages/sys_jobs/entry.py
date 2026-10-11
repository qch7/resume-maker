"""任务协调的注册、生命周期入口"""

from resume_maker.plugins.support import dependency, publish


def activate(context):
    """发布带所有者、配置代次的持久任务协调器"""
    from resume_maker.infrastructure.task_supervisor import TaskSupervisor
    from resume_maker.plugin_packages.sys_jobs.configuration import Settings

    supervisor = publish(
        context,
        "tasks",
        TaskSupervisor(
            dependency(context, "db"),
            context.host.task_context,
            context.host.prepare_task,
            policy=Settings.model_validate(context.config),
        ),
        observed=False,
    )
    context.lifecycle(supervisor.start, supervisor.stop)
