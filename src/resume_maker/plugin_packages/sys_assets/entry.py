"""资源目录的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish


def activate(context):
    """为插件持有不可变资源目录及事务内登记接口"""
    from resume_maker.infrastructure.assets import Assets

    service = Assets(dependency(context, "db"), dependency(context, "assets.backend"))
    publish(context, "assets", service)
