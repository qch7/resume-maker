"""隐私保护的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """创建每实例隐私存储，独立于任何模型供应商启停"""
    from resume_maker.infrastructure.privacy_contributions import PrivacyContributions
    from resume_maker.integrations.privacy_gateway import PrivacyGateway
    from resume_maker.integrations.privacy_store import PrivacyStore
    from resume_maker.plugin_packages.sys_privacy.services.privacy import Privacy

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
    routes(context, "resume_maker.plugin_packages.sys_privacy.routes.privacy")
