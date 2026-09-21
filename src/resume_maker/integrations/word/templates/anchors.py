"""分离共用文字段落的浮动绘图锚点；保留图形、坐标和组合关系"""

from lxml import etree

from resume_maker.integrations.word.ooxml import NS, w

WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def separate_anchors(root, *, paragraph_relative=False) -> bool:
    """给混合段落中的浮动图形独立锚点；文字重复区不再包含照片或其他栏目标题"""
    changed = False
    for paragraph in list(root.iter(w("p"))):
        drawings = [
            node
            for node in paragraph.iter(w("drawing"))
            if next(node.iterancestors(w("p")), None) is paragraph
        ]
        floating = [
            node
            for node in drawings
            if node.xpath(
                "./wp:anchor[wp:positionV[@relativeFrom='page' or @relativeFrom='margin'"
                + (" or @relativeFrom='paragraph'" if paragraph_relative else "")
                + "] "
                "and wp:positionH[@relativeFrom='page' or @relativeFrom='margin']]",
                namespaces={"wp": WP},
            )
        ]
        text = any(
            node.text and next(node.iterancestors(w("p")), None) is paragraph
            for node in paragraph.iter(w("t"))
        )
        if not floating or (not text and len(drawings) == 1):
            continue
        for drawing in floating:
            anchor_paragraph = etree.Element(w("p"))
            properties = etree.SubElement(anchor_paragraph, w("pPr"))
            etree.SubElement(properties, w("keepNext"))
            spacing = etree.SubElement(properties, w("spacing"))
            for key, value in {
                "before": "0",
                "after": "0",
                "line": "1",
                "lineRule": "exact",
            }.items():
                spacing.set(w(key), value)
            run = etree.SubElement(anchor_paragraph, w("r"))
            run.append(drawing)
            paragraph.addprevious(anchor_paragraph)
            changed = True
        # 空运行不影响版式；保留可能存在的分节、书签和其他原生控制节点
    return changed


def page_positioned(block) -> bool:
    """页面绝对定位的个人图形应固定在开头且不能随其偶然借用的栏目锚点移动"""
    return bool(
        block.xpath(".//wp:anchor/wp:positionV[@relativeFrom='page']", namespaces={**NS, "wp": WP})
    )
