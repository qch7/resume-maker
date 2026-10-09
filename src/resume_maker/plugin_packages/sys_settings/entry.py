"""系统设置的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """发布正式设置及实例配置，模型和业务设置由扩展另行贡献路由"""
    from resume_maker.plugin_packages.sys_settings.services.settings import Settings

    config = context.host.bootstrap["config"]
    publish(context, "config", config, observed=False)
    publish(context, "settings", Settings(dependency(context, "db"), config.data_dir))
    routes(context, "resume_maker.plugin_packages.sys_settings.routes.settings")
