"""模板适配的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """注册模板工作副本和填充能力，不强制依赖模型连接"""
    from resume_maker.integrations.word.templates.fill import fill_template
    from resume_maker.plugin_packages.ext_template_adapter.services.template_records import (
        TemplateRecords,
    )
    from resume_maker.plugin_packages.ext_template_adapter.services.templates.tasks import Templates
    from resume_maker.sdk.documents import DocumentEngine, generate_docx

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

    publish(context, "template.records", TemplateRecords(), observed=False)
    service = publish(
        context,
        "templates",
        Templates(
            dependency(context, "resume"),
            dependency(context, "config").data_dir,
            None,
            registry=dependency(context, "document.registry"),
            storage=dependency(context, "db"),
            assets=dependency(context, "assets"),
        ),
    )
    context.scope.barriers.append(service.stop)
    routes(context, "resume_maker.plugin_packages.ext_template_adapter.routes.templates")
