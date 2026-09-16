"""校验证书文件，生成本地分页预览和供视觉识别使用的图片。"""

from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps, UnidentifiedImageError

from resume_maker.core.errors import Problem

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 12
EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
IMAGE_FORMATS = {"PNG", "JPEG", "WEBP", "BMP", "TIFF"}


def prepare_certificate(raw: bytes, filename: str, directory: Path) -> dict:
    """按实际内容解码文件，限制页数与像素；原件和预览均使用固定文件名。"""
    suffix = Path(filename).suffix.lower()
    if suffix not in EXTENSIONS:
        raise Problem("支持 PDF、PNG、JPG、WebP、BMP 和 TIFF 文件。", 415)
    if not raw or len(raw) > MAX_BYTES:
        raise Problem("证书不能为空，单个文件不得超过 20 MB。", 413)
    texts = []
    try:
        if suffix == ".pdf":
            if not raw.lstrip().startswith(b"%PDF-"):
                raise Problem("文件内容不是有效的 PDF。", 415)
            with pymupdf.open(stream=raw, filetype="pdf") as document:
                if document.needs_pass:
                    raise Problem("请先移除 PDF 密码，再上传证书。")
                if not 1 <= len(document) <= MAX_PAGES:
                    raise Problem("每份证书 PDF 支持 1–12 页，请将不同证书分别上传。")
                for index, page in enumerate(document):
                    scale = min(2, 2000 / max(page.rect.width, page.rect.height, 1))
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                    pixmap.save(directory / f"page-{index + 1}.png")
                    texts.append(page.get_text()[:12000])
                pages = len(document)
        else:
            with Image.open(BytesIO(raw)) as source:
                if source.format not in IMAGE_FORMATS:
                    raise Problem("图片内容不是受支持的格式。", 415)
                if getattr(source, "n_frames", 1) != 1:
                    raise Problem("请将多页或动态图片转为 PDF，或拆分为单张图片上传。")
                if source.width * source.height > 40_000_000:
                    raise Problem("图片超过 4000 万像素，请缩小后上传。")
                normalized = ImageOps.exif_transpose(source).convert("RGBA")
                normalized.thumbnail((2000, 2000))
                image = Image.new("RGB", normalized.size, "white")
                image.paste(normalized, mask=normalized.getchannel("A"))
                image.save(directory / "page-1.png")
                pages = 1
    except Problem:
        raise
    except (
        ValueError,
        RuntimeError,
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        raise Problem("文件损坏或无法读取，请重新导出 PDF 或图片后上传。", 415) from exc
    (directory / ("original" + suffix)).write_bytes(raw)
    return {"pages": pages, "extension": suffix, "text": "\n\n".join(texts)[:30000]}
