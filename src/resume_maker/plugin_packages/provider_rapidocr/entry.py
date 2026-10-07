"""RapidOCR的注册和生命周期入口"""

from resume_maker.plugins.support import publish


def activate(context):
    """登记本地 OCR 引擎，实际模型按现有线程锁延迟加载"""
    from resume_maker.plugin_packages.provider_rapidocr.configuration import Settings
    from resume_maker.plugin_packages.provider_rapidocr.local_ocr import LocalOCR

    backend = LocalOCR(Settings.model_validate(context.config))
    context.scope.barriers.append(backend.close)
    publish(context, "ocr.backend", backend.read_document, observed=False)
