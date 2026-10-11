"""执行策略、材料隔离的注册、生命周期入口"""

from resume_maker.plugins.support import dependency, publish


def activate(context):
    """按提供方实际强制能力签发任务策略"""
    from resume_maker.infrastructure.execution import Sandbox

    publish(
        context,
        "sandbox",
        Sandbox(dependency(context, "execution"), dependency(context, "sandbox.backend")),
    )
