"""Word 精确排版的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish


def activate(context):
    """将精确排版器附接到文档流程，DOCX 生成保持独立"""
    from resume_maker.integrations.document_importers import importer
    from resume_maker.plugin_packages.ext_word.integrations.word.controlled import ControlledWord
    from resume_maker.sdk.documents import DocumentRenderer

    engine = ControlledWord(
        dependency(context, "execution"), dependency(context, "sandbox"), context.generation
    )
    context.scope.barriers.append(engine.close)
    context.contribute(
        "documents.importers", "ext.word/import", importer("word", converter=engine.convert)
    )
    publish(context, "word.renderer", engine.render, observed=False)
    context.contribute(
        "documents.renderers", "ext.word/default", DocumentRenderer("1.0.0", engine.render)
    )
