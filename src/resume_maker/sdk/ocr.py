"""OCR 提供方的公开字典契约和资源边界"""

import math
import threading
from pathlib import Path
from typing import Protocol, TypedDict

from resume_maker.sdk.model import Cancelled, ProviderError

OCR_MAX_PAGES = 12
OCR_MAX_TEXT_CHARS = 100_000
OCR_MAX_BLOCKS = 6000
OCR_MAX_FILE_BYTES = 20 * 1024 * 1024
SOURCE_IMAGE_MAX_PIXELS = 40_000_000
OCR_REVIEW_CONFIDENCE = 0.85


class OCRBlock(TypedDict):
    """一行文字，box 为原页面左上角起算的归一化 x0、y0、x1、y1"""

    text: str
    box: list[float]
    confidence: float


class OCRPage(TypedDict):
    """页面按原文顺序排列，尺寸使用提取坐标所在页面的单位"""

    width: float
    height: float
    blocks: list[OCRBlock]
    method: str


class OCRDocument(TypedDict):
    """有效文字按行换行和页面双换行汇总，空文档通过 ProviderError 报告"""

    pages: list[OCRPage]
    text: str
    seconds: float
    needs_review: bool
    notice: str


class OCRBackend(Protocol):
    """同步识别只能在实际执行结束后返回，取消通过 Cancelled 报告"""

    def read_document(self, path: Path, cancelled: threading.Event) -> OCRDocument:
        """读取本机原件，不发送给模型，返回前再次检查取消"""
        ...

    def close(self) -> None:
        """等待当前执行结束后释放提供方资源"""
        ...


def validate_ocr_document(value: object) -> OCRDocument:
    """在公共能力边界拒绝无效坐标、非有限数字和超限文字"""

    def number(item, *, minimum=0, maximum=None):
        """布尔值不能充当坐标或置信度"""
        return (
            type(item) in {int, float}
            and math.isfinite(item)
            and item >= minimum
            and (maximum is None or item <= maximum)
        )

    def invalid():
        """统一报告结构错误，避免异常包含识别原文"""
        raise ProviderError("OCR 返回值不符合公开契约，请检查插件提供方。")

    if not isinstance(value, dict) or not isinstance(value.get("pages"), list):
        invalid()
    pages = value["pages"]
    if not 1 <= len(pages) <= OCR_MAX_PAGES:
        invalid()
    total, review, texts = 0, False, []
    for page in pages:
        if (
            not isinstance(page, dict)
            or not number(page.get("width"), minimum=1)
            or not number(page.get("height"), minimum=1)
            or not isinstance(page.get("method"), str)
            or not page["method"]
            or not isinstance(page.get("blocks"), list)
        ):
            invalid()
        total += len(page["blocks"])
        if total > OCR_MAX_BLOCKS:
            invalid()
        lines = []
        for block in page["blocks"]:
            if not isinstance(block, dict):
                invalid()
            box = block.get("box")
            text = block.get("text")
            if (
                not isinstance(text, str)
                or not text.strip()
                or not isinstance(box, list)
                or len(box) != 4
                or not all(number(point, maximum=1) for point in box)
                or box[0] >= box[2]
                or box[1] >= box[3]
                or not number(block.get("confidence"), maximum=1)
            ):
                invalid()
            lines.append(text)
            review |= block["confidence"] < OCR_REVIEW_CONFIDENCE
        texts.append("\n".join(lines))
    text = "\n\n".join(texts)
    if not text.strip():
        raise ProviderError("OCR 未识别到可用文字，请核对原件或手动录入。")
    if (
        len(text) > OCR_MAX_TEXT_CHARS
        or value.get("text") != text
        or not number(value.get("seconds"))
        or type(value.get("needs_review")) is not bool
        or (review and not value["needs_review"])
        or not isinstance(value.get("notice"), str)
    ):
        invalid()
    return value


class ValidatedOCR:
    """消费入口统一校验第三方返回值并阻止取消后的结果发布"""

    def __init__(self, backend: OCRBackend):
        """只保存当前计划绑定的提供方"""
        self.backend = backend

    def read_document(self, path: Path, cancelled: threading.Event) -> OCRDocument:
        """在实际调用前后检查取消，提供方保留自己的停止屏障"""
        if cancelled.is_set():
            raise Cancelled("OCR 已取消。")
        value = self.backend.read_document(path, cancelled)
        if cancelled.is_set():
            raise Cancelled("OCR 已取消。")
        return validate_ocr_document(value)
