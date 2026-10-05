"""平台执行后端的注册和生命周期入口"""

from resume_maker.plugins.support import publish


def activate(context):
    """使用 Windows Job Object 或 POSIX 进程组的本机执行提供方"""
    from resume_maker.integrations.providers.process import execute

    publish(context, "execution.backend", execute, observed=False)
