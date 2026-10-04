"""独立领域测试的显式文档装配，生产服务只接受插件注入"""

from resume_maker.integrations.word.full_resume import write_full_resume
from resume_maker.integrations.word.rendering import render_word as native_render
from resume_maker.integrations.word.templates.fill import fill_template
from resume_maker.services.documents import Documents as DocumentService
from resume_maker.services.resume_previews import ResumePreviews as PreviewService

render_word = native_render


def renderer(*args):
    """替身可在同一测试中模拟 Word 失败后恢复"""
    return render_word(*args)


def options(values):
    """测试明确选择内置、模板和 Word 能力，不依赖服务私自加载其他插件"""
    return {
        "engine": write_full_resume,
        "template_engine": fill_template,
        "templates": True,
        "render": renderer,
        **values,
    }


def Documents(*args, **kwargs):
    """用真实领域服务和测试指定的文档能力构造导出器"""
    return DocumentService(*args, **options(kwargs))


def ResumePreviews(*args, **kwargs):
    """用相同装配构造预览器，正式输入冻结和取消逻辑保持真实实现"""
    return PreviewService(*args, **options(kwargs))
