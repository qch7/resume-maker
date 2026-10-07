"""系统日志的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """建立独立日志库并恢复历史采集状态"""
    from resume_maker.infrastructure.activity import ActivityLog
    from resume_maker.infrastructure.observability import install_logging
    from resume_maker.plugin_packages.sys_activity.configuration import Settings

    config = context.host.bootstrap["config"]
    db = dependency(context, "db")
    log = ActivityLog(
        config.data_dir / "logs" / "activity.sqlite",
        secrets=(config.token,),
        policy=Settings.model_validate(context.config),
    )
    db.activity = log
    log.import_history(db)
    install_logging()
    publish(context, "activity", log, observed=False)
    routes(context, "resume_maker.plugin_packages.sys_activity.routes.activity")
