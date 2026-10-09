"""AI 编排的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """所有 AI 消费者使用共享隐私入口及所选模型传输"""
    from resume_maker.integrations.privacy_gateway import ModelCapacity
    from resume_maker.plugin_packages.ext_ai_runtime.configuration import Settings

    policy = Settings.model_validate(context.config)
    provider = context.host.bootstrap.get("provider") or dependency(context, "privacy.gateway")(
        dependency(context, "model.transport"),
        ocr=dependency(context, "ocr") if "ocr" in context.host.services else None,
        images="ext.import-image" in context.host.selected,
        capacity=ModelCapacity(
            policy.max_parallel_calls, policy.max_waiting_calls, policy.wait_timeout_seconds
        ),
    )
    publish(context, "provider", provider, observed=False)
    settings = dependency(context, "settings")
    context.effect(settings.attach_provider(provider))
    routes(context, "resume_maker.plugin_packages.ext_ai_runtime.routes.settings")
