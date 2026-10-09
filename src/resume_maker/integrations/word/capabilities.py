"""文档工具默认报告未装配，实际 Word 执行由公开渲染贡献注入"""


def word_process(source, output, mode="render"):
    """缺少渲染或转换贡献时返回可解释的能力提示"""
    return "未装配 Word 自动处理能力。"


def render_word(source, output):
    """基础 DOCX 生成不隐式启动可选 Word 实现"""
    return None, word_process(source, output)


def convert_word(source, output):
    """旧格式转换要求调用方显式传入转换器"""
    return word_process(source, output, "convert")
