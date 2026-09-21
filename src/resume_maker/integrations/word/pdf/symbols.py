"""识别字体编码的小图标，保留其实际外观以免导出时依赖缺失的图标字体"""

import re
import unicodedata

import pymupdf


def font_symbols(page):
    """只接受独立符号或已知图标字体的短私用字符，正文乱码仍由视觉恢复处理"""
    symbols = []
    for block in page.get_text("dict", flags=0)["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if not text or len(text) > 4 or text in {"•", "·", "●", "▪"}:
                    continue
                icon_font = re.search(
                    r"awesome|wingdings|webdings|symbol|material|icon", span["font"], re.IGNORECASE
                )
                visible = any(unicodedata.category(c) == "So" for c in text)
                symbolic = all(unicodedata.category(c) in {"So", "Cf", "Mn"} for c in text)
                private = icon_font and all(0xE000 <= ord(c) <= 0xF8FF for c in text)
                if (visible and symbolic) or private:
                    box = pymupdf.Rect(span["bbox"]) & page.rect
                    if not box.is_empty:
                        symbols.append((box, text))
    return symbols
