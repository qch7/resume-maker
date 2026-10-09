"""按处理阶段区分文档资源边界，不加载可选图像和 PDF 依赖"""

from resume_maker.sdk.ocr import (
    OCR_MAX_BLOCKS as OCR_MAX_BLOCKS,
)
from resume_maker.sdk.ocr import (
    OCR_MAX_FILE_BYTES as OCR_MAX_FILE_BYTES,
)
from resume_maker.sdk.ocr import (
    OCR_MAX_PAGES as OCR_MAX_PAGES,
)
from resume_maker.sdk.ocr import (
    OCR_MAX_TEXT_CHARS as OCR_MAX_TEXT_CHARS,
)
from resume_maker.sdk.ocr import (
    SOURCE_IMAGE_MAX_PIXELS as SOURCE_IMAGE_MAX_PIXELS,
)

CERTIFICATE_MAX_BYTES = 20 * 1024 * 1024
CERTIFICATE_MAX_PAGES = 12
TEMPLATE_MAX_BYTES = 100_000_000
DOCX_MAX_UNCOMPRESSED_BYTES = 100_000_000
SAFE_IMAGE_MAX_PIXELS = 20_000_000
SAFE_PAGE_MAX_BYTES = 20_000_000
MOSAIC_SOURCE_MAX_BYTES = 20 * 1024 * 1024
CERTIFICATE_TEXT_PER_PAGE_CHARS = 12_000
CERTIFICATE_TEXT_TOTAL_CHARS = 30_000


def import_limits(purpose):
    """界面和后端读取同一用途的上传边界，模板页数由格式处理器核验"""
    return {
        "max_bytes": CERTIFICATE_MAX_BYTES if purpose == "certificate" else TEMPLATE_MAX_BYTES,
        "max_pages": CERTIFICATE_MAX_PAGES if purpose == "certificate" else None,
        "max_image_pixels": SOURCE_IMAGE_MAX_PIXELS,
    }
