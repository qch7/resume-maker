"""图片导入的注册和生命周期入口"""

from resume_maker.plugins.support import publish


def activate(context):
    """注册图片解码入口，PDF 库不参与图片导入"""
    from resume_maker.integrations.certificates import prepare_certificate
    from resume_maker.integrations.document_importers import importer

    publish(context, "import.image", prepare_certificate, observed=False)
    context.contribute("documents.importers", "ext.import-image/default", importer("image"))
