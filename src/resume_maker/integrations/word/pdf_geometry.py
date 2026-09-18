"""记录 PDF 恢复来源和局部坐标，供填入真实资料时关联图标与字段。"""

import json

PDF = "urn:resume-maker:pdf"
BOX = f"{{{PDF}}}box"
TEXT = f"{{{PDF}}}text"
ROLE = f"{{{PDF}}}role"
SOURCE = f"{{{PDF}}}source"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
LEGACY_LABELS = {
    "PDF 固定装饰（图标、底色或线条）",
    "PDF 原图或照片",
    "PDF 页面底色",
}


def mark_paragraph(paragraph, block):
    """保留逐文字片段的原坐标，不把用户填写的新资料写入 PDF 来源标记。"""
    paragraph.set(BOX, json.dumps(list(block.bbox)))
    paragraph.set(
        TEXT,
        json.dumps(
            [(span.text, list(span.bbox)) for line in block.lines for span in line.spans],
            ensure_ascii=False,
        ),
    )


def recovered_pdf(root):
    """只启用带来源标记或本程序旧版素材说明的恢复模板，普通 Word 不进入此流程。"""
    return root.get(SOURCE) == "1" or any(
        legacy_asset(node) for node in root.iter(f"{{{WP}}}docPr")
    )


def recovered_layout(root):
    """仅原生 PDF 或新版图片空间恢复模板复用自适应排版，旧 Word 分支保持原样。"""
    return root.get(SOURCE) == "image-v1" or recovered_pdf(root)


def legacy_asset(node):
    """旧版 PDF 的浮动素材提供来源证据，已经排好的行内图标不当作待恢复模板。"""
    return (
        node.tag == f"{{{WP}}}docPr"
        and node.get("descr") in LEGACY_LABELS
        and node.getparent().tag == f"{{{WP}}}anchor"
    )


def clear_pdf_metadata(root):
    """成品不携带旧模板文字与坐标；原始模板快照仍保留证据供下次重新填充。"""
    for node in root.iter():
        for key in list(node.attrib):
            if key.startswith(f"{{{PDF}}}"):
                del node.attrib[key]


def rectangle(node):
    """读取可选来源坐标；外部 Word 去掉标记时返回空值，不猜测无依据的位置。"""
    try:
        value = json.loads(node.get(BOX, "null"))
        return tuple(float(x) for x in value) if value is not None and len(value) == 4 else None
    except (ValueError, TypeError):
        return None
