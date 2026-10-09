"""记录 PDF 恢复来源和局部坐标，供填入真实资料时关联图标和字段"""

import json

PDF = "urn:resume-maker:pdf"
BOX = f"{{{PDF}}}box"
TEXT = f"{{{PDF}}}text"
ROLE = f"{{{PDF}}}role"
SOURCE = f"{{{PDF}}}source"
PRIVATE = f"{{{PDF}}}private"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def mark_paragraph(paragraph, block):
    """在来源标记中保存原文字片段的坐标"""
    paragraph.set(BOX, json.dumps(list(block.bbox)))
    paragraph.set(
        TEXT,
        json.dumps(
            [(span.text, list(span.bbox)) for line in block.lines for span in line.spans],
            ensure_ascii=False,
        ),
    )


def recovered_pdf(root):
    """仅为明确标记来源的 PDF 恢复模板启用排版"""
    return root.get(SOURCE) == "1"


def recovered_layout(root):
    """仅原生 PDF 或新版图片空间恢复模板复用自适应排版，旧 Word 分支保持原样"""
    return root.get(SOURCE) == "image-v1" or recovered_pdf(root)


def clear_pdf_metadata(root):
    """成品不携带旧模板文字和坐标，原始模板快照仍保留证据供下次重新填充"""
    for node in root.iter():
        for key in list(node.attrib):
            if key.startswith(f"{{{PDF}}}"):
                del node.attrib[key]


def rectangle(node):
    """读取来源坐标并在标记缺失时返回空值"""
    try:
        value = json.loads(node.get(BOX, "null"))
        return tuple(float(x) for x in value) if value is not None and len(value) == 4 else None
    except (ValueError, TypeError):
        return None
