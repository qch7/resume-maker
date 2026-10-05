"""系统执行的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish


def activate(context):
    """通过选择的平台后端执行已签发的任务授权"""
    from resume_maker.infrastructure.execution import Execution

    publish(context, "execution", Execution(dependency(context, "execution.backend")))
