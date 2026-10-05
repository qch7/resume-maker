"""AI 编排的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """所有 AI 消费者使用共享隐私入口及所选模型传输"""
    provider = context.host.bootstrap.get("provider") or dependency(context, "privacy.gateway")(
        dependency(context, "model.transport"),
        ocr=dependency(context, "ocr") if "ocr" in context.host.services else None,
        images="ext.import-image" in context.host.selected,
    )
    publish(context, "provider", provider, observed=False)
    settings = dependency(context, "settings")
    context.effect(settings.attach_provider(provider))
    routes(context, "resume_maker.plugin_packages.ext_ai_runtime.routes.settings")
