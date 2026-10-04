"""可选能力入口，服务、路由和后台执行归属相同插件作用域"""

from resume_maker.plugins.support import dependency, publish, routes


def ai_runtime(context):
    """所有 AI 消费者使用共享隐私入口及所选模型传输"""
    provider = context.host.bootstrap.get("provider") or dependency(context, "privacy.gateway")(
        dependency(context, "model.transport"),
        ocr=dependency(context, "ocr") if "ocr" in context.host.services else None,
        images="ext.import-image" in context.host.selected,
    )
    publish(context, "provider", provider, observed=False)
    settings = dependency(context, "settings")
    settings.provider = provider
    context.effect(lambda: setattr(settings, "provider", None))
    routes(context, "settings", only={"provider_settings", "inspect_provider", "check_provider"})


def conversations(context):
    """注册 AI 会话和经历分析任务，停用后保留已存历史及草稿"""
    from resume_maker.plugins.queries import conversations as query
    from resume_maker.services.conversations import Conversations
    from resume_maker.services.jobs import Jobs

    catalog = dependency(context, "catalog")
    conversations = publish(context, "conversations", Conversations(catalog))
    catalog.project_initializers[context.instance_id] = conversations.initialize_project
    context.effect(lambda: catalog.project_initializers.pop(context.instance_id, None))
    queue = publish(
        context,
        "jobs",
        Jobs(
            dependency(context, "db"),
            catalog,
            dependency(context, "config").data_dir,
            dependency(context, "provider"),
            conversations=conversations,
        ),
    )
    queue.execution_queue = task_queue(context)
    context.lifecycle(queue.start, queue.stop)
    context.effect(
        dependency(context, "tasks").attach(
            context.instance_id,
            lambda: queue.db.all(
                "SELECT id,status AS state FROM jobs WHERE status IN ('queued','running')"
            ),
            queue.cancel,
        )
    )
    routes(context, "conversations")
    routes(context, "jobs")
    context.contribute("workspace.queries", "conversations", query)


def source_code(context):
    """注册只读来源扫描和绑定接口，手工项目不依赖来源能力"""
    from resume_maker.integrations.sources import scan_collection

    publish(context, "sources", scan_collection, observed=False)
    routes(context, "projects", only={"scan", "update_sources"})


def honors(context):
    """荣誉资料库可独立手工维护，识别任务由另一个插件附接"""
    from resume_maker.plugins.queries import honors as query
    from resume_maker.services.honor_links import resolve_honor_document
    from resume_maker.services.honors import Honors

    service = publish(
        context,
        "honors",
        Honors(dependency(context, "db"), dependency(context, "config").data_dir, None),
    )
    context.scope.barriers.append(service.stop)
    service.import_registry = dependency(context, "document.registry")
    routes(context, "honors", exclude={"recognize_honor"})
    catalog = dependency(context, "resume")
    catalog.honor_resolver = resolve_honor_document
    from resume_maker.services.honor_links import preserve_honor_snapshots

    context.before_deactivate.append(lambda: preserve_honor_snapshots(catalog.db))
    context.effect(lambda: setattr(catalog, "honor_resolver", None))
    context.contribute("workspace.queries", "honors", query)


def honor_recognition(context):
    """仅选择识别能力时启动荣誉后台线程"""
    service = dependency(context, "honors")
    service.provider = dependency(context, "provider")
    service.execution_queue = task_queue(context)
    context.effect(lambda: setattr(service, "execution_queue", None))
    context.effect(service.stopped.clear)
    context.lifecycle(service.start, service.stop)
    context.effect(
        dependency(context, "tasks").attach(
            context.instance_id,
            lambda: [
                {"id": row["id"], "state": row["status"]}
                for row in service.list()
                if row["status"] in {"queued", "running"}
            ],
            service.cancel,
        )
    )
    context.effect(lambda: setattr(service, "provider", None))
    routes(context, "honors", only={"recognize_honor"})


def template_adapter(context):
    """注册模板工作副本和填充能力，不强制依赖模型连接"""
    from resume_maker.integrations.word.templates.fill import fill_template
    from resume_maker.sdk.documents import DocumentEngine
    from resume_maker.services.document_inputs import generate_docx
    from resume_maker.services.templates.tasks import Templates

    def generate(output, inputs):
        """模板引擎消费冻结原件及映射，不在生成过程中重新查询模板库"""
        resume, projects, template = inputs.values()
        generate_docx(
            output,
            resume["document"],
            projects,
            engine=None,
            template_data=inputs.template_bytes,
            plan=template["mapping"]["plan"],
            template_engine=fill_template,
        )

    context.contribute(
        "documents.engines",
        "ext.template-adapter/default",
        DocumentEngine("1.0.0", generate, accepts_template=True),
    )

    service = publish(
        context,
        "templates",
        Templates(dependency(context, "resume"), dependency(context, "config").data_dir, None),
    )
    context.scope.barriers.append(service.stop)
    service.import_registry = dependency(context, "document.registry")
    service.renderer = None
    service.converter = None
    for name in ("documents", "resume_previews"):
        target = dependency(context, name)
        target.templates_enabled = True
        target.template_engine = fill_template
        context.effect(lambda target=target: setattr(target, "templates_enabled", False))
        context.effect(lambda target=target: setattr(target, "template_engine", None))
    routes(
        context,
        "templates",
        exclude={
            "template_library",
            "update_library_item",
            "create_template_category",
            "delete_library_template",
            "restore_library_template",
            "delete_template_category",
            "template_thumbnail",
            "analyze_template",
        },
    )


def template_library(context):
    """注册模板组织、回收站和数据清理生命周期"""
    from resume_maker.plugins.queries import templates as query
    from resume_maker.services.templates.library import TemplateLibrary

    service = publish(
        context,
        "template_library",
        TemplateLibrary(
            dependency(context, "resume"),
            dependency(context, "config").data_dir,
            dependency(context, "templates"),
            dependency(context, "resume_previews"),
        ),
    )
    service.renderer = None
    context.lifecycle(service.start, service.stop)
    routes(
        context,
        "templates",
        only={
            "template_library",
            "update_library_item",
            "create_template_category",
            "delete_library_template",
            "restore_library_template",
            "delete_template_category",
            "template_thumbnail",
        },
    )
    context.contribute("workspace.queries", "templates", query)


def template_ai(context):
    """为模板分析附接统一模型出口"""
    service = dependency(context, "templates")
    service.provider = dependency(context, "provider")
    service.execution_queue = task_queue(context)
    context.scope.barriers.append(service.execution_queue.close)
    context.effect(lambda: setattr(service, "execution_queue", None))
    context.effect(
        dependency(context, "tasks").attach(
            context.instance_id,
            lambda: [
                {"id": row["id"], "state": row["status"]}
                for row in service.list_tasks()
                if row["status"] == "running"
            ],
            service.cancel,
        )
    )
    context.effect(lambda: setattr(service, "provider", None))
    routes(context, "templates", only={"analyze_template"})


def word(context):
    """将精确排版器附接到文档流程，DOCX 生成保持独立"""
    from resume_maker.integrations.document_importers import importer
    from resume_maker.integrations.word.controlled import ControlledWord
    from resume_maker.sdk.documents import DocumentRenderer

    engine = ControlledWord(
        dependency(context, "execution"), dependency(context, "sandbox"), context.generation
    )
    context.scope.barriers.append(engine.close)
    context.contribute(
        "documents.importers", "ext.word/import", importer("word", converter=engine.convert)
    )
    publish(context, "word.renderer", engine.render, observed=False)
    context.contribute(
        "documents.renderers", "ext.word/default", DocumentRenderer("1.0.0", engine.render)
    )
    for name in ("documents", "resume_previews", "templates", "template_library"):
        if name not in context.host.services:
            continue
        target = dependency(context, name)
        target.renderer = engine.render
        context.effect(lambda target=target: setattr(target, "renderer", None))
        if name == "templates":
            target.converter = engine.convert
            context.effect(lambda target=target: setattr(target, "converter", None))


def recruitment(context):
    """招聘插件拥有业务入口和设置贡献，停用不删除收藏数据"""
    from resume_maker.services.recruitment import Recruitment

    publish(context, "recruitment", Recruitment(dependency(context, "db")))
    routes(context, "recruitment")
    routes(context, "settings", only={"recruitment_settings", "save_recruitment_settings"})


def native_shell(context):
    """注册明确由用户触发的本机文件选择和来源定位"""
    routes(context, "system", only={"select_path"})
    routes(context, "projects", only={"reveal_source"})


def task_queue(context):
    """固定处理器所有者、插件版本和提供方绑定，由系统统一持有执行租约"""
    return dependency(context, "tasks").scope(
        context.instance_id,
        context.generation,
        {
            name: {"id": owner, "version": context.host.manifests[owner].version}
            for name, owner in context.host.resolution.providers.items()
        },
        context.manifest.version,
    )
