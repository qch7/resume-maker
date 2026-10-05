"""执行策略与材料隔离的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish


def activate(context):
    """按提供方实际强制能力签发任务策略"""
    from resume_maker.infrastructure.execution import Sandbox

    publish(
        context,
        "sandbox",
        Sandbox(dependency(context, "execution"), dependency(context, "sandbox.backend")),
    )
