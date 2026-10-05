"""文档流程的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish, routes


def activate(context):
    """组装文档流程，内置引擎独立于 Word 和模板扩展"""
    from resume_maker.plugin_packages.sys_documents.services.document_registry import (
        DocumentRegistry,
    )
    from resume_maker.plugin_packages.sys_documents.services.documents import Documents
    from resume_maker.plugin_packages.sys_documents.services.resume_previews import ResumePreviews

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
    routes(context, "resume_maker.plugin_packages.sys_documents.routes.resumes")
