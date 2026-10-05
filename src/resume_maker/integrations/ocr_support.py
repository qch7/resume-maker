"""文档恢复和隐私网关复用的 OCR 预算、取消及原生文字工具"""

import pymupdf

from resume_maker.sdk.model import Cancelled, ProviderError

MAX_PAGES = 12
REVIEW_SCORE = 0.85


class OCRBudget:
    """累计模板回退页面的 OCR 开销，同一页重试只计一次"""

    def __init__(self):
        """每份模板独立记录页数、文字数和行数"""
        self.pages = {}

    def register(self, key, blocks):
        """在模型发送前拒绝超限页面，可靠文字页不占用额度"""
        self.pages[key] = (sum(len(row["text"]) for row in blocks), len(blocks))
        if len(self.pages) > MAX_PAGES:
            raise ProviderError("模板需要 OCR 的页面超过 12 页，请拆分后重试。")
        if (
            sum(row[0] for row in self.pages.values()) > 100000
            or sum(row[1] for row in self.pages.values()) > 6000
        ):
            raise ProviderError("OCR 文字超过单次处理上限，请拆分文档。")


def check_cancelled(cancelled):
    """在页面和识别阶段边界检查取消，避免发布已取消结果"""
    if cancelled.is_set():
        raise Cancelled("本地 OCR 已取消。")


def native_blocks(page):
    """优先使用 PDF 的可靠文字层，保留每一行的比例坐标"""
    if any(span.get("type") == 3 for span in page.get_texttrace()):
        # 隐藏 OCR 层可能残留错字，改由当前可见像素恢复文字
        return []
    blocks = []
    width, height = page.rect.width, page.rect.height
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text and "\ufffd" not in text:
                x0, y0, x1, y1 = pymupdf.Rect(line["bbox"]) * page.rotation_matrix
                box = [
                    max(0, x0 / width),
                    max(0, y0 / height),
                    min(1, x1 / width),
                    min(1, y1 / height),
                ]
                if box[0] < box[2] and box[1] < box[3]:
                    blocks.append({"text": text, "box": box, "confidence": 1.0})
    return blocks
