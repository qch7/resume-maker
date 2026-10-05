"""内置 DOCX 引擎的注册和生命周期入口"""

from resume_maker.plugins.support import publish


def activate(context):
    """发布只依赖本地 OOXML 的内置简历引擎"""
    from resume_maker.integrations.document_importers import importer
    from resume_maker.integrations.word.full_resume import write_full_resume
    from resume_maker.sdk.documents import DocumentEngine

    def generate(output, inputs):
        """内置引擎只消费冻结内容，保持预览和导出的字段规则一致"""
        resume, projects, _template = inputs.values()
        write_full_resume(output, resume["document"], projects)

    context.contribute("documents.importers", "sys.docx/import", importer("docx"))
    publish(context, "docx", write_full_resume, observed=False)
    context.contribute("documents.engines", "sys.docx/default", DocumentEngine("1.0.0", generate))
