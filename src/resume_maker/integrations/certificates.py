"""校验证书文件，生成本地分页预览和供视觉识别使用的图片"""

from io import BytesIO
from pathlib import Path

from resume_maker.core.errors import Problem
from resume_maker.integrations.document_limits import (
    CERTIFICATE_MAX_BYTES as MAX_BYTES,
)
from resume_maker.integrations.document_limits import (
    CERTIFICATE_MAX_PAGES as MAX_PAGES,
)
from resume_maker.integrations.document_limits import (
    CERTIFICATE_TEXT_PER_PAGE_CHARS,
    CERTIFICATE_TEXT_TOTAL_CHARS,
    SOURCE_IMAGE_MAX_PIXELS,
)
from resume_maker.integrations.media_formats import IMAGE_EXTENSIONS, IMAGE_FORMATS

EXTENSIONS = {".pdf", *IMAGE_EXTENSIONS}


def prepare_certificate(raw: bytes, filename: str, directory: Path) -> dict:
    """按实际内容解码文件，限制页数和像素，原件和预览均使用固定文件名"""
    suffix = Path(filename).suffix.lower()
    if suffix not in EXTENSIONS:
        raise Problem("支持 PDF、PNG、JPG、WebP、BMP 和 TIFF 文件。", 415)
    if not raw or len(raw) > MAX_BYTES:
        raise Problem(f"证书不能为空，单个文件不得超过 {MAX_BYTES // (1024 * 1024)} MiB。", 413)
    texts = []
    try:
        if suffix == ".pdf":
            import pymupdf

            if not raw.lstrip().startswith(b"%PDF-"):
                raise Problem("文件内容不是有效的 PDF。", 415)
            with pymupdf.open(stream=raw, filetype="pdf") as document:
                if document.needs_pass:
                    raise Problem("请先移除 PDF 密码，再上传证书。")
                if not 1 <= len(document) <= MAX_PAGES:
                    raise Problem(f"每份证书 PDF 支持 1–{MAX_PAGES} 页，请将不同证书分别上传。")
                for index, page in enumerate(document):
                    scale = min(2, 2000 / max(page.rect.width, page.rect.height, 1))
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                    pixmap.save(directory / f"page-{index + 1}.png")
                    texts.append(page.get_text()[:CERTIFICATE_TEXT_PER_PAGE_CHARS])
                pages = len(document)
        else:
            normalize_image(raw, directory)
            pages = 1
    except Problem:
        raise
    except (
        ValueError,
        RuntimeError,
        OSError,
    ) as exc:
        raise Problem("文件损坏或无法读取，请重新导出 PDF 或图片后上传。", 415) from exc
    (directory / ("original" + suffix)).write_bytes(raw)
    return {
        "pages": pages,
        "extension": suffix,
        "text": "\n\n".join(texts)[:CERTIFICATE_TEXT_TOTAL_CHARS],
    }


def normalize_image(raw, directory):
    """仅图片解码时装载图像库并转换其大小异常"""
    from PIL import Image, ImageOps

    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in IMAGE_FORMATS:
                raise Problem("图片内容不是受支持的格式。", 415)
            if getattr(source, "n_frames", 1) != 1:
                raise Problem("请将多页或动态图片转为 PDF，或拆分为单张图片上传。")
            if source.width * source.height > SOURCE_IMAGE_MAX_PIXELS:
                raise Problem("图片超过 4000 万像素，请缩小后上传。")
            normalized = ImageOps.exif_transpose(source).convert("RGBA")
            normalized.thumbnail((2000, 2000))
            image = Image.new("RGB", normalized.size, "white")
            image.paste(normalized, mask=normalized.getchannel("A"))
            image.save(directory / "page-1.png")

    except Image.DecompressionBombError as exc:
        raise Problem("图片像素超过安全解码范围。", 413) from exc
