"""使用随包模型在本机提取中英文文字和坐标，不连接云端 OCR"""

import math
import threading
import time
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

from resume_maker.integrations.providers.base import Cancelled, ProviderError

LOCK = threading.Lock()
ENGINE = None
MAX_PAGES = 12
MAX_PIXELS = 40_000_000
REVIEW_SCORE = 0.85
BASE_SIDE = 960
RETRY_SIDE = 2000


def check_cancelled(cancelled):
    """在页面和识别阶段边界检查取消，避免发布已取消结果"""
    if cancelled.is_set():
        raise Cancelled("本地 OCR 已取消。")


def engine():
    """延迟加载单份 PP-OCRv4 移动模型，限制 CPU 线程及重复模型内存"""
    global ENGINE
    if ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        ENGINE = RapidOCR(
            intra_op_num_threads=2,
            inter_op_num_threads=1,
            det_limit_side_len=736,
            det_limit_type="max",
            text_score=0.3,
        )
    return ENGINE


def recognize(image, cancelled, *, adaptive=True):
    """默认使用轻量检测分辨率，仅对空结果或低置信度页面复核一次"""
    import numpy as np

    check_cancelled(cancelled)
    if image.width * image.height > MAX_PIXELS:
        raise ProviderError("OCR 图片超过 4000 万像素，请缩小后重试。")
    source = ImageOps.exif_transpose(image).convert("RGBA")
    original = Image.new("RGBA", source.size, "white")
    original.alpha_composite(source)
    original = original.convert("RGB")
    image = original.copy()
    image.thumbnail((BASE_SIDE, BASE_SIDE))
    pixels = np.asarray(image)
    while not LOCK.acquire(timeout=0.1):
        check_cancelled(cancelled)
    try:
        check_cancelled(cancelled)
        reader = engine()
        result, _ = reader(pixels)
        refined = False
        small_text = any(
            max(p[1] for p in row[0]) - min(p[1] for p in row[0]) <= 14 for row in result or []
        )
        if (
            adaptive
            and max(original.size) > BASE_SIDE
            and (
                len(result or []) <= 2 or small_text or any(row[2] < REVIEW_SCORE for row in result)
            )
        ):
            check_cancelled(cancelled)
            larger = original.copy()
            larger.thumbnail((RETRY_SIDE, RETRY_SIDE))
            alternate, _ = reader(np.asarray(larger))
            # 高分辨率复核只在覆盖率不降且平均置信度提升时替换首次结果
            if alternate and (
                not result
                or (
                    len(alternate) >= len(result)
                    and sum(r[2] for r in alternate) / len(alternate)
                    >= sum(r[2] for r in result) / len(result) - 0.03
                )
            ):
                result = alternate
                image = larger
            refined = True
        check_cancelled(cancelled)
    finally:
        LOCK.release()
    blocks = []
    for points, text, score, *_ in result or []:
        if not text.strip():
            continue
        xs, ys = [float(p[0]) for p in points], [float(p[1]) for p in points]
        box = [
            max(0, min(xs) / image.width),
            max(0, min(ys) / image.height),
            min(1, max(xs) / image.width),
            min(1, max(ys) / image.height),
        ]
        if all(math.isfinite(v) for v in [*box, score]) and box[0] < box[2] and box[1] < box[3]:
            blocks.append({"text": text.strip(), "box": box, "confidence": round(float(score), 4)})
    return {
        "width": image.width,
        "height": image.height,
        "blocks": blocks,
        "method": "ocr-refined" if refined else "ocr",
    }


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


def overlaps(left, right):
    """去除文字层已经覆盖的 OCR 行，避免重复文字及识别错字覆盖原文"""
    a, b = left["box"], right["box"]
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return area > 0.3 * min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))


def pdf_page(page, cancelled):
    """扫描页及含大块图片的混合页才启动 OCR，纯文字页直接提取"""
    blocks = native_blocks(page)
    image_area = sum(pymupdf.Rect(item["bbox"]).get_area() for item in page.get_image_info())
    need_ocr = (
        sum(len(row["text"]) for row in blocks) < 12 or image_area > page.rect.get_area() * 0.15
    )
    if not need_ocr:
        return {
            "width": page.rect.width,
            "height": page.rect.height,
            "blocks": blocks,
            "method": "pdf-text",
        }
    scale = min(3, 2400 / max(page.rect.width, page.rect.height, 1))
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    with Image.open(BytesIO(pixmap.tobytes("png"))) as image:
        result = recognize(image, cancelled)
    result["blocks"] = blocks + [
        row for row in result["blocks"] if not any(overlaps(row, native) for native in blocks)
    ]
    result["blocks"].sort(key=lambda row: (round(row["box"][1], 2), row["box"][0]))
    return result


def read_document(path, cancelled):
    """统一处理本地 PDF 和图片，限制页数、字数和文件大小且不返回原始像素"""
    path = Path(path)
    check_cancelled(cancelled)
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ProviderError("OCR 文件超过 20 MB，请拆分后重试。")
    started = time.monotonic()
    try:
        if path.suffix.lower() == ".pdf":
            with pymupdf.open(path) as document:
                if document.needs_pass or not 1 <= len(document) <= MAX_PAGES:
                    raise ProviderError("本地 OCR 支持未加密的 1–12 页 PDF。")
                pages = []
                for page in document:
                    check_cancelled(cancelled)
                    pages.append(pdf_page(page, cancelled))
        else:
            with Image.open(path) as image:
                if getattr(image, "n_frames", 1) != 1:
                    raise ProviderError("多帧图片请拆分或转为 PDF 后识别。")
                pages = [recognize(image, cancelled)]
    except (OSError, ValueError, RuntimeError, Image.DecompressionBombError) as exc:
        raise ProviderError("本地 OCR 无法读取文档，请检查文件或手动录入。") from exc
    text = "\n\n".join("\n".join(row["text"] for row in page["blocks"]) for page in pages)
    if not text.strip():
        raise ProviderError("本地 OCR 未识别到可用文字，原图未发送，请手动录入。")
    if len(text) > 100000 or sum(len(page["blocks"]) for page in pages) > 6000:
        raise ProviderError("OCR 文字超过单次处理上限，请拆分文档。")
    return {
        "pages": pages,
        "text": text,
        "seconds": round(time.monotonic() - started, 3),
        "needs_review": any(
            row["confidence"] < REVIEW_SCORE for page in pages for row in page["blocks"]
        ),
        "notice": "文字和位置由本机提取；照片、印章、装饰未提供给模型。"
        "OCR 可能漏字或误认，需核对原件。",
    }
