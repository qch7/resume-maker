"""插件管理的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """发布运行状态及可审查的组合管理入口"""
    from resume_maker.plugins.discovery import discover
    from resume_maker.runtime.downloads import Downloads
    from resume_maker.runtime.manager import PluginManager
    from resume_maker.runtime.upgrades import Upgrades

    manager = context.host.bootstrap.get("plugin_manager")
    if manager is None:
        manager = PluginManager(context.host, context.host.bootstrap["state_store"], discover()[2])
        context.host.bootstrap["plugin_manager"] = manager
    manager.downloads = Downloads(dependency(context, "config").data_dir)
    manager.upgrades = Upgrades(manager)
    context.scope.barriers.append(manager.downloads.close)
    context.scope.barriers.append(manager.upgrades.close)
    publish(
        context,
        "plugins",
        manager,
        observed=False,
    )
    routes(context, "resume_maker.plugin_packages.sys_plugins.routes.plugins")
