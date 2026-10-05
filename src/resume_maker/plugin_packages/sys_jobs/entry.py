"""任务协调的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish


def activate(context):
    """发布带所有者和配置代次的持久任务协调器"""
    from resume_maker.infrastructure.task_supervisor import TaskSupervisor

    supervisor = publish(
        context,
        "tasks",
        TaskSupervisor(
            dependency(context, "db"), context.host.task_context, context.host.prepare_task
        ),
        observed=False,
    )
    context.lifecycle(supervisor.start, supervisor.stop)
