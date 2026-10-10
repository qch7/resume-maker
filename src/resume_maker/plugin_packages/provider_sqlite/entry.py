"""SQLite 后端的注册和生命周期入口"""

from resume_maker.plugins.support import publish


def activate(context):
    """为工作区建立 SQLite 事务后端"""
    from resume_maker.infrastructure.database import Database
    from resume_maker.plugin_packages.provider_sqlite.configuration import Settings

    config = context.host.bootstrap["config"]
    publish(
        context,
        "storage.backend",
        Database(
            config.data_dir / "resume.db",
            plugins={context.host.definition_id(key) for key in context.host.selected},
            policy=Settings.model_validate(context.config),
        ),
        observed=False,
    )
