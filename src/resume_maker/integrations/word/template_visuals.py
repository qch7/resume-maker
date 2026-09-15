"""为陌生模板提供真实整页图和 OOXML 版式证据，不由字段名称推测坐标。"""

import pymupdf
from lxml import etree

from resume_maker.integrations.providers.base import Cancelled
from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.rendering import word_process


def attributes(node):
    """保留原始属性及单位，不把 Word 的相对位置误报为页面绝对坐标。"""
    return {etree.QName(key).localname: value for key, value in node.attrib.items()}


def layout_context(package):
    """提供实际换行、制表位和排版容器，字符偏移与精确引文使用同一段落文字。"""
    paragraphs, containers = {}, {}
    for identifier, paragraph in package.nodes.items():
        if paragraph.tag != w("p"):
            continue
        position, controls = 0, []
        for node in paragraph.iter():
            if next(node.iterancestors(w("p")), None) is not paragraph:
                continue
            if node.tag == w("t"):
                position += len(node.text or "")
            elif node.tag in {w("br"), w("cr"), w("tab")} and any(
                parent.tag == w("r") for parent in node.iterancestors()
            ):
                controls.append(
                    {"offset": position, "kind": etree.QName(node).localname, **attributes(node)}
                )
        properties = paragraph.find(w("pPr"))
        value = {"controls": controls}
        if properties is not None:
            for key in ("tabs", "ind", "jc", "spacing", "framePr", "sectPr", "bidi"):
                node = properties.find(w(key))
                if node is not None:
                    value[key] = (
                        [
                            {"kind": etree.QName(child).localname, **attributes(child)}
                            for child in node
                        ]
                        if len(node)
                        else attributes(node)
                    )
        container = paragraph.getparent()
        container_id = package.ids.get(container, "")
        value["container"] = container_id
        containers[container_id] = {"kind": etree.QName(container).localname}
        if container.tag == w("tc"):
            width = container.find("w:tcPr/w:tcW", NS)
            height = container.getparent().find("w:trPr/w:trHeight", NS)
            if width is not None:
                containers[container_id]["width"] = attributes(width)
            if height is not None:
                containers[container_id]["row_height"] = attributes(height)
        paragraphs[identifier] = value
    return {
        "units": "OOXML 原始单位；制表位、缩进、间距为 twip，20 twip = 1 pt",
        "paragraphs": paragraphs,
        "containers": containers,
    }


def source_pages(source, directory, flag):
    """仅渲染源模板副本供模型看整页；失败和超出图片预算的页数明确返回。"""
    if flag.is_set():
        raise Cancelled("模板分析已取消。")
    output = directory / "source-layout"
    output.mkdir(exist_ok=True)
    pdf = output / "source.pdf"
    error = word_process(source, pdf)
    if flag.is_set():
        raise Cancelled("模板分析已取消。")
    if error:
        return [], {"available": False, "reason": error}, ["未能读取源模板的整页版式：" + error]
    try:
        with pymupdf.open(pdf) as document:
            paths, pages = [], []
            # 整页证据与最多四张图片拼图共同限制单轮附件体积；未展示页面必须告知模型。
            for index in range(min(len(document), 6)):
                page = document[index]
                image = output / f"source-page-{index + 1}.png"
                page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6)).save(image)
                paths.append(image)
                pages.append({"page": index + 1, "image": image.name})
            omitted = max(0, len(document) - len(pages))
            notices = (
                [
                    f"源模板共 {len(document)} 页，整页视觉识别仅展示前 {len(pages)} 页，"
                    "后续页按结构清单识别。"
                ]
                if omitted
                else []
            )
            return (
                paths,
                {"available": True, "total": len(document), "pages": pages, "omitted": omitted},
                notices,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        return (
            [],
            {"available": False, "reason": str(exc)},
            ["源模板整页图生成失败，继续使用结构清单识别。"],
        )
