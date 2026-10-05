"""备份恢复的注册和生命周期入口"""

from resume_maker.plugins.support import publish, routes


def activate(context):
    """发布备份服务，附件枚举不依赖业务插件是否激活"""
    from resume_maker.infrastructure.storage import create_backup

    publish(context, "backup", create_backup, observed=False)
    routes(context, "resume_maker.plugin_packages.sys_backup.routes.system")
