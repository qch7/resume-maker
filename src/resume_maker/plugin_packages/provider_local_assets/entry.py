"""本地资源后端的注册和生命周期入口"""

from resume_maker.plugins.support import publish


def activate(context):
    """提供显式的数据资源根目录"""
    publish(context, "assets.backend", context.host.bootstrap["config"].data_dir, observed=False)
