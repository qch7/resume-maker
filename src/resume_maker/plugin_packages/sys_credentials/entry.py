"""凭据借用的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish


def activate(context):
    """发布不透明凭据引用，最小系统无需模型登录"""
    publish(context, "credentials", dependency(context, "credentials.backend"), observed=False)
