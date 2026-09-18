"""检查图片恢复中资料区与重复栏目是否共用容器，避免通过映射检查却跳过顶部重排。"""

from resume_maker.core.errors import Problem
from resume_maker.integrations.word.ooxml import w
from resume_maker.integrations.word.template_layout import child_in


def check_image_header(package, plan):
    """独立页首表格不与经历重复区混用；带栏目标题的真正双栏容器继续保留原结构。"""
    body = package.parts["word/document.xml"].find(w("body"))
    titles = [
        package.node(field.node)
        for field in plan.fields
        if field.target.startswith("section-title:")
    ]
    edge = min(
        (body.index(child_in(node, body)) for node in titles if body in node.iterancestors()),
        default=len(body),
    )
    personal = [
        package.node(field.node) for field in plan.fields if field.target.startswith("personal.")
    ]
    for region in plan.repeats:
        start = package.node(region.start)
        if body not in start.iterancestors():
            continue
        root = child_in(start, body)
        if root.tag != w("tbl") or body.index(root) >= edge:
            continue
        if any(root in node.iterancestors() for node in personal):
            raise Problem(
                f"图片顶部资料与“{region.section}”重复区共用表格，无法独立重排。"
                "请将顶部摘要映射为个人字段，并为该栏目选择独立的经历样本；"
                "不能把顶部单个学历或工作摘要当作完整栏目重复区。"
            )
