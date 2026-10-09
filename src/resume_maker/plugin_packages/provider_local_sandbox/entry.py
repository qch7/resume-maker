"""本地材料会话的注册和生命周期入口"""

from resume_maker.integrations.providers.sandbox import LocalSandbox
from resume_maker.plugins.support import publish


def activate(context):
    """注册应用材料约束提供方，保持 OS 隔离能力明确为不可用"""
    publish(context, "sandbox.backend", LocalSandbox(), observed=False)
