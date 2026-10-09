"""PDF 导入的注册和生命周期入口"""

from resume_maker.plugins.support import publish


def activate(context):
    """注册 PDF 解码入口，OCR 识别由独立插件负责"""
    from resume_maker.integrations.certificates import prepare_certificate
    from resume_maker.integrations.document_importers import importer

    publish(context, "import.pdf", prepare_certificate, observed=False)
    context.contribute("documents.importers", "ext.import-pdf/default", importer("pdf"))
    context.contribute(
        "documents.importers", "ext.import-pdf/scanned-docx", importer("scanned-docx")
    )
