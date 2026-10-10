"""系统存储的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish


def activate(context):
    """将选定的数据库提供方作为工作区事务服务发布"""
    from resume_maker.infrastructure.data_catalog import data_blockers, synchronize_catalog
    from resume_maker.infrastructure.instance_data import InstanceDataStore

    db = dependency(context, "storage.backend")

    def definitions(selected):
        """插件 schema 属于定义，多个实例的资料由实例存储按身份隔离"""
        return {
            context.host.definition_id(key): context.host.definitions[
                context.host.definition_id(key)
            ]
            for key in selected
        }

    reasons = data_blockers(
        db, definitions(context.host.selected), context.host.bootstrap.get("packages", {})
    )
    context.host.block_unavailable(
        {
            key: reasons[context.host.definition_id(key)]
            for key in context.host.selected
            if context.host.definition_id(key) in reasons
        }
    )

    def synchronize(selected):
        """保留定义级数据描述，实例停用不会删除对应的命名空间资料"""
        db.ensure_schemas(definitions(selected))
        synchronize_catalog(db, definitions(selected), context.host.bootstrap.get("packages", {}))

    synchronize(context.host.selected)
    context.host.bootstrap["synchronize_data"] = synchronize
    context.effect(lambda: context.host.bootstrap.pop("synchronize_data", None))
    publish(context, "db", db, observed=False)
    publish(
        context,
        "storage.instances",
        lambda owner, scope_id, temporary=False: InstanceDataStore(db, owner, scope_id, temporary),
        observed=False,
    )
