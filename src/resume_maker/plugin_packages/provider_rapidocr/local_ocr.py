"""使用随包模型在本机提取中英文文字和坐标，不连接云端 OCR"""

import math
import threading
import time
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

from resume_maker.infrastructure.observability import operation
from resume_maker.integrations.document_limits import (
    OCR_MAX_BLOCKS,
    OCR_MAX_FILE_BYTES,
    OCR_MAX_TEXT_CHARS,
    SOURCE_IMAGE_MAX_PIXELS,
)
from resume_maker.integrations.ocr_support import (
    MAX_PAGES,
    REVIEW_SCORE,
    check_cancelled,
    native_blocks,
)
from resume_maker.plugin_packages.provider_rapidocr.configuration import Settings
from resume_maker.sdk.model import ProviderError

MAX_PIXELS = SOURCE_IMAGE_MAX_PIXELS
LOCK_POLL_SECONDS = 0.1
RETRY_CONFIDENCE_TOLERANCE = 0.03
OVERLAP_RATIO = 0.3
NATIVE_TEXT_MIN_CHARS = 12
PDF_IMAGE_AREA_RATIO = 0.15


class LocalOCR:
    """模型和锁归属插件实例，配置变更不会复用旧模型或修改其他应用"""

    def __init__(self, settings=None):
        """只冻结配置，实际模型在第一次识别时装载"""
        self.settings = settings or Settings()
        self.lock = threading.RLock()
        self._engine = None
        self.closed = False

    def engine(self):
        """模型构造和识别共用实例锁，CPU 参数在装载前固定"""
        with self.lock:
            if self.closed:
                raise ProviderError("本地 OCR 实例已停止，请使用当前活动实例。")
            if self._engine is None:
                from rapidocr_onnxruntime import RapidOCR

                self._engine = RapidOCR(
                    intra_op_num_threads=self.settings.intra_op_num_threads,
                    inter_op_num_threads=self.settings.inter_op_num_threads,
                    det_limit_side_len=self.settings.detection_side,
                    det_limit_type="max",
                    text_score=self.settings.text_score,
                )
            return self._engine

    def recognize(self, image, cancelled, *, adaptive=True):
        """识别消费本实例的尺寸和复核策略"""
        return recognize(image, cancelled, adaptive=adaptive, backend=self)

    def read_document(self, path, cancelled):
        """文档识别期间沿用当前实例的冻结配置"""
        return read_document(path, cancelled, backend=self)

    def close(self):
        """识别真正结束后释放当前实例的模型引用"""
        with self.lock:
            self.closed = True
            self._engine = None


DEFAULT_BACKEND = LocalOCR()


def engine():
    """延迟加载单份 PP-OCRv4 移动模型，限制 CPU 线程及重复模型内存"""
    return DEFAULT_BACKEND.engine()


def recognize(image, cancelled, *, adaptive=True, backend=None):
    """默认使用轻量检测分辨率，仅对空结果或低置信度页面复核一次"""
    import numpy as np

    selected = backend or DEFAULT_BACKEND
    settings, lock = selected.settings, selected.lock
    check_cancelled(cancelled)
    if image.width * image.height > MAX_PIXELS:
        raise ProviderError("OCR 图片超过 4000 万像素，请缩小后重试。")
    source = ImageOps.exif_transpose(image).convert("RGBA")
    original = Image.new("RGBA", source.size, "white")
    original.alpha_composite(source)
    original = original.convert("RGB")
    image = original.copy()
    image.thumbnail((settings.base_side, settings.base_side))
    pixels = np.asarray(image)
    while not lock.acquire(timeout=LOCK_POLL_SECONDS):
        check_cancelled(cancelled)
    try:
        check_cancelled(cancelled)
        reader = selected.engine() if backend is not None else engine()
        result, _ = reader(pixels)
        refined = False
        small_text = any(
            max(p[1] for p in row[0]) - min(p[1] for p in row[0]) <= settings.small_text_height
            for row in result or []
        )
        if (
            adaptive
            and settings.adaptive_retry_enabled
            and max(original.size) > settings.base_side
            and settings.retry_side > settings.base_side
            and (
                len(result or []) <= settings.sparse_result_count
                or small_text
                or any(row[2] < REVIEW_SCORE for row in result)
            )
        ):
            check_cancelled(cancelled)
            larger = original.copy()
            larger.thumbnail((settings.retry_side, settings.retry_side))
            alternate, _ = reader(np.asarray(larger))
            # 高分辨率复核只在覆盖率不降且平均置信度提升时替换首次结果
            if alternate and (
                not result
                or (
                    len(alternate) >= len(result)
                    and sum(r[2] for r in alternate) / len(alternate)
                    >= sum(r[2] for r in result) / len(result) - RETRY_CONFIDENCE_TOLERANCE
                )
            ):
                result = alternate
                image = larger
            refined = True
        check_cancelled(cancelled)
    finally:
        lock.release()
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


def overlaps(left, right):
    """去除文字层已经覆盖的 OCR 行，避免重复文字及识别错字覆盖原文"""
    a, b = left["box"], right["box"]
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return area > OVERLAP_RATIO * min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))


def pdf_page(page, cancelled, *, backend=None):
    """扫描页及含大块图片的混合页才启动 OCR，纯文字页直接提取"""
    blocks = native_blocks(page)
    settings = (backend or DEFAULT_BACKEND).settings
    image_area = sum(pymupdf.Rect(item["bbox"]).get_area() for item in page.get_image_info())
    need_ocr = (
        sum(len(row["text"]) for row in blocks) < NATIVE_TEXT_MIN_CHARS
        or image_area > page.rect.get_area() * PDF_IMAGE_AREA_RATIO
    )
    if not need_ocr:
        return {
            "width": page.rect.width,
            "height": page.rect.height,
            "blocks": blocks,
            "method": "pdf-text",
        }
    scale = min(
        settings.pdf_render_scale,
        settings.pdf_render_side / max(page.rect.width, page.rect.height, 1),
    )
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    with Image.open(BytesIO(pixmap.tobytes("png"))) as image:
        result = (
            backend.recognize(image, cancelled)
            if backend is not None
            else recognize(image, cancelled)
        )
    result["blocks"] = blocks + [
        row for row in result["blocks"] if not any(overlaps(row, native) for native in blocks)
    ]
    result["blocks"].sort(key=lambda row: (round(row["box"][1], 2), row["box"][0]))
    return result


@operation("ocr.read_document", "system")
def read_document(path, cancelled, *, backend=None):
    """统一处理本地 PDF 和图片，限制页数、字数和文件大小且不返回原始像素"""
    path = Path(path)
    check_cancelled(cancelled)
    if path.stat().st_size > OCR_MAX_FILE_BYTES:
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
                    pages.append(pdf_page(page, cancelled, backend=backend))
        else:
            with Image.open(path) as image:
                if getattr(image, "n_frames", 1) != 1:
                    raise ProviderError("多帧图片请拆分或转为 PDF 后识别。")
                pages = [
                    backend.recognize(image, cancelled)
                    if backend is not None
                    else recognize(image, cancelled)
                ]
    except (OSError, ValueError, RuntimeError, Image.DecompressionBombError) as exc:
        raise ProviderError("本地 OCR 无法读取文档，请检查文件或手动录入。") from exc
    text = "\n\n".join("\n".join(row["text"] for row in page["blocks"]) for page in pages)
    if not text.strip():
        raise ProviderError("本地 OCR 未识别到可用文字，原图未发送，请手动录入。")
    if (
        len(text) > OCR_MAX_TEXT_CHARS
        or sum(len(page["blocks"]) for page in pages) > OCR_MAX_BLOCKS
    ):
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
