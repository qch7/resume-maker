"""系统插件入口，各项依赖和生命周期由独立清单限定"""

from resume_maker.plugins.support import dependency, publish, routes


def storage(context):
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


def settings(context):
    """发布正式设置及实例配置，模型和业务设置由扩展另行贡献路由"""
    from resume_maker.services.settings import Settings

    config = context.host.bootstrap["config"]
    publish(context, "config", config, observed=False)
    publish(context, "settings", Settings(dependency(context, "db"), config.data_dir))
    routes(context, "settings", only={"settings", "resume_defaults", "save_resume_defaults"})


def activity(context):
    """建立独立日志库并恢复历史采集状态"""
    from resume_maker.infrastructure.activity import ActivityLog
    from resume_maker.infrastructure.observability import install_logging

    config = context.host.bootstrap["config"]
    db = dependency(context, "db")
    log = ActivityLog(config.data_dir / "logs" / "activity.sqlite", secrets=(config.token,))
    db.activity = log
    log.import_history(db)
    install_logging()
    publish(context, "activity", log, observed=False)
    routes(context, "activity")


def drafts(context):
    """发布具有实体版本和恢复代次的持久草稿服务"""
    from resume_maker.services.workspace_storage import WorkspaceStorage

    publish(context, "workspace_storage", WorkspaceStorage(dependency(context, "db")))
    routes(context, "workspace_storage")


def privacy(context):
    """创建每实例隐私存储，独立于任何模型供应商启停"""
    from resume_maker.infrastructure.privacy_contributions import PrivacyContributions
    from resume_maker.integrations.privacy_gateway import PrivacyGateway
    from resume_maker.integrations.privacy_store import PrivacyStore
    from resume_maker.services.privacy import Privacy

    db = dependency(context, "db")
    rules = PrivacyContributions(db, context.host.collection)
    store = publish(context, "privacy.store", PrivacyStore(db, rules), observed=False)
    context.health(rules.entries)

    def gateway(runner, *, ocr=None, images=False):
        """绑定选定传输，任务副本和脱敏还原保持归系统所有"""
        return PrivacyGateway(privacy=store, runner=runner, ocr=ocr, images=images)

    publish(context, "privacy.gateway", gateway, observed=False)

    def runtime_state():
        """隐私状态反映当前能力，停用模型或 OCR 不再显示虚假保护实现"""
        services = context.host.resolution.providers
        return {
            "transport": services.get("model.transport", "disabled"),
            "isolation": "read-only-material-tools"
            if "model.transport" in services
            else "inactive",
            "images": "local-ocr" if "ocr" in services else "disabled",
            "ocr": {"engine": services.get("ocr", "disabled")},
            "rules": rules.describe(),
        }

    publish(context, "privacy", Privacy(db, store, runtime_state=runtime_state))
    routes(context, "privacy")


def experience(context):
    """发布经历、固定修订及草稿事务，默认不创建 AI 会话"""
    from resume_maker.services.catalog import Catalog
    from resume_maker.services.projects import Projects

    catalog = publish(
        context,
        "catalog",
        Catalog(dependency(context, "db"), assets=dependency(context, "assets")),
    )
    publish(context, "projects", Projects(catalog))
    routes(context, "projects", exclude={"scan", "update_sources", "reveal_source"})


def resume(context):
    """发布固定引用的简历编辑和历史接口"""
    from resume_maker.services.resume_sources import ResumeSources
    from resume_maker.services.resumes import Resumes

    sources = ResumeSources(dependency(context, "db"), context.host.collection)
    service = publish(
        context,
        "resume",
        Resumes(
            dependency(context, "catalog"),
            storage=dependency(context, "db"),
            sources=sources,
            assets=dependency(context, "assets"),
        ),
    )
    context.before_deactivate.append(service.preserve_sources)
    context.health(sources.entries)
    routes(
        context,
        "resumes",
        only={
            "new_resume",
            "save_resume",
            "delete_resume",
            "resume_sources",
            "resume_source_items",
        },
    )


def documents(context):
    """组装文档流程，内置引擎独立于 Word 和模板扩展"""
    from resume_maker.services.document_registry import DocumentRegistry
    from resume_maker.services.documents import Documents
    from resume_maker.services.resume_previews import ResumePreviews

    catalog = dependency(context, "resume")
    directory = dependency(context, "config").data_dir
    engine = dependency(context, "docx")

    def provenance(owner):
        """重试绑定插件版本、已安装产物摘要和配置摘要，配置原文不进入业务记录"""
        from resume_maker.runtime.state import fingerprint

        location = context.host.package_location(owner)
        return {
            "plugin_version": context.host.manifests[owner].version,
            "artifact_sha256": location.name if location else None,
            "config_sha256": fingerprint(context.host.configs.get(owner, {})),
        }

    registry = DocumentRegistry(context.host.collection, provenance)
    documents = Documents(
        catalog,
        directory,
        storage=dependency(context, "db"),
        assets=dependency(context, "assets"),
        render=None,
        templates=False,
        engine=engine,
        registry=registry,
        runtime_snapshot=lambda: {
            "generation": context.host.generation,
            "providers": dict(context.host.resolution.providers),
            "plugins": {key: context.host.manifests[key].version for key in context.host.selected},
        },
    )
    previews = ResumePreviews(
        catalog, directory, render=None, templates=False, engine=engine, registry=registry
    )
    publish(context, "document.registry", registry, observed=False)
    publish(context, "documents", documents)
    publish(context, "resume_previews", previews)
    context.effect(previews.stop)
    routes(
        context,
        "resumes",
        exclude={
            "new_resume",
            "save_resume",
            "delete_resume",
            "resume_sources",
            "resume_source_items",
        },
    )


def docx(context):
    """发布只依赖本地 OOXML 的内置简历引擎"""
    from resume_maker.integrations.document_importers import importer
    from resume_maker.integrations.word.full_resume import write_full_resume
    from resume_maker.sdk.documents import DocumentEngine

    def generate(output, inputs):
        """内置引擎只消费冻结内容，保持预览和导出的字段规则一致"""
        resume, projects, _template = inputs.values()
        write_full_resume(output, resume["document"], projects)

    context.contribute("documents.importers", "sys.docx/import", importer("docx"))
    publish(context, "docx", write_full_resume, observed=False)
    context.contribute("documents.engines", "sys.docx/default", DocumentEngine("1.0.0", generate))


def workbench(context):
    """建立工作台查询扩展点，系统页面只读取系统能力"""
    from resume_maker.services.workspace import Workspace

    publish(
        context,
        "workspace",
        Workspace(
            dependency(context, "db"),
            readers=[
                dependency(context, name).workspace_state
                for name in ("catalog", "resume", "settings")
            ],
            contributors=lambda: context.host.collection("workspace.queries"),
        ),
    )
    routes(context, "system", only={"state"})


def http(context):
    """提供本机 HTTP 宿主入口和公共健康诊断"""
    publish(context, "http", context.host, observed=False)
    routes(context, "system", only={"health", "shutdown"})


def backup(context):
    """发布备份服务，附件枚举不依赖业务插件是否激活"""
    from resume_maker.infrastructure.storage import create_backup

    publish(context, "backup", create_backup, observed=False)
    routes(context, "system", only={"backup"})


def plugins(context):
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
    routes(context, "plugins")


def assets(context):
    """为插件持有不可变资源目录及事务内登记接口"""
    from resume_maker.infrastructure.asset_migration import migrate_legacy_assets
    from resume_maker.infrastructure.assets import Assets

    service = Assets(dependency(context, "db"), dependency(context, "assets.backend"))
    migrate_legacy_assets(service)
    publish(context, "assets", service)


def execution(context):
    """通过选择的平台后端执行已签发的任务授权"""
    from resume_maker.infrastructure.execution import Execution

    publish(context, "execution", Execution(dependency(context, "execution.backend")))


def sandbox(context):
    """按提供方实际强制能力签发任务策略"""
    from resume_maker.infrastructure.execution import Sandbox

    publish(
        context,
        "sandbox",
        Sandbox(dependency(context, "execution"), dependency(context, "sandbox.backend")),
    )


def credentials(context):
    """发布不透明凭据引用，最小系统无需模型登录"""
    publish(context, "credentials", dependency(context, "credentials.backend"), observed=False)


def jobs(context):
    """发布带所有者和配置代次的持久任务协调器"""
    from resume_maker.infrastructure.task_supervisor import TaskSupervisor

    supervisor = publish(
        context,
        "tasks",
        TaskSupervisor(
            dependency(context, "db"), context.host.task_context, context.host.prepare_task
        ),
        observed=False,
    )
    context.lifecycle(supervisor.start, supervisor.stop)
