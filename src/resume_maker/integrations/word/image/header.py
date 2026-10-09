"""检查图片恢复中资料区和重复栏目是否共用容器以免通过映射检查却跳过顶部重排"""

import math

from resume_maker.core.errors import Problem
from resume_maker.integrations.providers.page_images import header_values
from resume_maker.integrations.word.ooxml import w
from resume_maker.integrations.word.pdf.geometry import PRIVATE, SOURCE, rectangle
from resume_maker.integrations.word.templates.layout import child_in


def private_image_text(package):
    """按分节重建图片和扫描 PDF 身份登记，重开任务后继续保护每页页首"""
    root = package.parts["word/document.xml"]
    legacy_image = root.get(SOURCE) == "image-v1"
    pages, nodes = [], []
    for child in root.find(w("body")):
        nodes.extend(child.iter(w("p")))
        section = child if child.tag == w("sectPr") else child.find(f"{w('pPr')}/{w('sectPr')}")
        if section is None:
            continue
        if legacy_image or section.get(SOURCE) == "image-v1":
            pages.append({"blocks": private_page_blocks(nodes, section)})
        nodes = []
    if not pages:
        return None
    return {
        "text": "\n".join(block["text"] for page in pages for block in page["blocks"]),
        "pages": pages,
    }


def private_page_blocks(nodes, section):
    """使用当前页纸张尺寸保护页首，未知或损坏坐标的文字整体保护"""
    size = section.find(w("pgSz"))
    width = float(size.get(w("w"), "11906")) / 20 if size is not None else 595.3
    height = float(size.get(w("h"), "16838")) / 20 if size is not None else 841.9
    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
        raise Problem("页面恢复模板的纸张尺寸无效，无法重新保护文字。")
    blocks = []
    for node in nodes:
        text = "".join(part.text or "" for part in node.iter(w("t"))).strip()
        if not text:
            continue
        box = rectangle(node)
        if box and (
            not all(math.isfinite(value) for value in box)
            or not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height)
        ):
            box = None
        blocks.append(
            {
                "text": text,
                "box": [value / (width if i % 2 == 0 else height) for i, value in enumerate(box)]
                if box
                else [0, 0, 1, 1],
                "confidence": 1.0 if box and node.get(PRIVATE) != "1" else 0.0,
            }
        )
    protected = header_values(blocks)
    for block in blocks:
        if block["text"] in protected:
            block["confidence"] = 0.0
    return blocks


def check_image_header(package, plan):
    """独立页首表格单独处理并保留含栏目标题的双栏结构"""
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
