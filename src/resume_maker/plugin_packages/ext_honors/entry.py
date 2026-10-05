"""荣誉库的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """荣誉资料库可独立手工维护，识别任务由另一个插件附接"""
    from resume_maker.plugin_packages.ext_honors.query import honors as query
    from resume_maker.plugin_packages.ext_honors.services.honor_links import resume_source
    from resume_maker.plugin_packages.ext_honors.services.honors import Honors
    from resume_maker.sdk.privacy import PrivacyRuleContribution, PrivacyValues

    def private_honors(reader):
        """本机证书资料登记身份和凭据，不把正文交给规则展示界面"""
        return PrivacyValues(
            private_data=tuple(
                row["value"]
                for row in reader.all("SELECT value_json FROM settings WHERE key LIKE 'honor:%'")
            )
        )

    context.contribute(
        "privacy.rule_contributions",
        "ext.honors/identities",
        PrivacyRuleContribution(
            "证书身份保护", "保护荣誉库中的获奖人、编号及结构化身份信息。", "1.0.0", private_honors
        ),
    )

    service = publish(
        context,
        "honors",
        Honors(
            dependency(context, "db"),
            dependency(context, "config").data_dir,
            None,
            preserve_sources=dependency(context, "resume").preserve_sources,
            assets=dependency(context, "assets"),
            registry=dependency(context, "document.registry"),
        ),
    )
    context.scope.barriers.append(service.stop)
    routes(context, "resume_maker.plugin_packages.ext_honors.routes.honors")
    context.contribute("resume.sources", "ext.honors/library", resume_source())
    context.contribute("workspace.queries", "honors", query)
