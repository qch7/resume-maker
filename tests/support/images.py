"""图片恢复和脱敏页面的合成样本"""

from io import BytesIO

import pymupdf
from PIL import Image, ImageDraw, PngImagePlugin

from resume_maker.domain.image_layout import ImageAsset, ImagePage, ImageText
from resume_maker.domain.templates import TemplatePlan, TextBinding
from resume_maker.integrations.providers import page_images
from tests.support.privacy import synthetic_image


def image_fixture(path, scale=2, left=False, font=None):
    """生成不同分辨率的独立样例，包含同行联系资料、左右头像和带白字的栏目底块"""
    texts, assets = [], []
    width, height = 595, 842
    font = font or pymupdf.Font("helv")
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=width, height=height)
        page.insert_font(fontname="FixtureFont", fontbuffer=font.buffer)
        for x, y, text, size in [
            (230, 50, "SAMPLE NAME", 20),
            (100, 80, "OLD PHONE", 11),
            (255, 80, "OLD EMAIL", 11),
            (100, 102, "OLD ROLE", 11),
            (45, 153, "SECTION", 12),
            (40, 182, "FIXED BODY", 11),
        ]:
            span_width = font.text_length(text, fontsize=size)
            texts.append(
                ImageText(
                    text=text,
                    font_name="Arial",
                    color="#FFFFFF" if text == "SECTION" else "#222222",
                    box=[
                        x / width,
                        (y - size * 0.75) / height,
                        (x + span_width) / width,
                        y / height,
                    ],
                )
            )
        for x, y in [(90, 76), (245, 76), (90, 98)]:
            page.draw_circle((x, y), 3, color=(0.2, 0.3, 0.4))
            assets.append(
                ImageAsset(
                    kind="icon",
                    box=[(x - 4) / width, (y - 4) / height, (x + 4) / width, (y + 4) / height],
                )
            )
        x = 35 if left else 500
        page.draw_rect((x, 25, x + 48, 89), fill=(0.2, 0.6, 0.8))
        assets.append(
            ImageAsset(kind="photo", box=[x / width, 25 / height, (x + 48) / width, 89 / height])
        )
        page.draw_rect((35, 137, 120, 159), fill=(0.1, 0.15, 0.2))
        assets.append(
            ImageAsset(
                kind="shape",
                color="#1A2633",
                box=[35 / width, 137 / height, 120 / width, 159 / height],
            )
        )
        for text in texts:
            x0, y0, x1, y1 = text.box
            size = (x1 - x0) * width / font.text_length(text.text, fontsize=1)
            page.insert_text(
                (x0 * width, y1 * height),
                text.text,
                fontname="FixtureFont",
                fontsize=size,
                color=(1, 1, 1) if text.text == "SECTION" else (0, 0, 0),
            )
        page.get_pixmap(matrix=pymupdf.Matrix(scale, scale)).save(path)
    return ImagePage(texts=texts, assets=assets)


def source_plan(package):
    """按原文字段含义生成合成映射"""
    rows = package.inventory()["nodes"]
    fields = []
    for quote, target in [
        ("SAMPLE NAME", "personal.name"),
        ("OLD PHONE", "personal.phone"),
        ("OLD EMAIL", "personal.email"),
        ("OLD ROLE", "personal.job_title"),
        ("SECTION", "section-title:项目经历"),
    ]:
        row = next(row for row in rows if row["kind"] == "p" and quote in row["text"])
        fields.append(TextBinding(node=row["id"], quote=quote, target=target))
    photos = [row["id"] for row in rows if row["kind"] == "image" and "photo" in row["text"]]
    claimed = {field.node for field in fields} | set(photos)
    return TemplatePlan(
        summary="图片测试",
        fields=fields,
        repeats=[],
        photos=photos,
        remove=[],
        warnings=[],
        keep=[
            row["id"] for row in rows if row["kind"] in {"p", "image"} and row["id"] not in claimed
        ],
    )


def forbidden_fallback(*args):
    """原生夹具不得意外进入有损视觉恢复"""
    raise AssertionError("原生 PDF 不应触发视觉恢复")


def quiet(*args):
    """忽略测试进度以免测试输出包含原文资料"""


def page_fixture(path, monkeypatch):
    """创建带敏感文字、白字底块和独立人像的合成页面及本地 OCR 结果"""
    layout = image_fixture(path)
    with Image.open(path) as source, Image.open(BytesIO(synthetic_image())) as photo:
        image = source.copy()
        asset = next(asset for asset in layout.assets if asset.kind == "photo")
        box = page_images.pixel_box(asset.box, image.size)
        image.paste(photo.resize((box[2] - box[0], box[3] - box[1])), box[:2])
        # 未识别的小字也不能作为原始像素从文字块以外直接外发
        ImageDraw.Draw(image).text((700, 800), "MISSED-PRIVATE-TEXT", fill="black")
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("private", "PAGE-PRIVATE-METADATA")
        image.save(path, pnginfo=metadata)
    local = {
        "pages": [
            {
                "blocks": [
                    {"text": row.text, "box": row.box, "confidence": 0.99} for row in layout.texts
                ]
            }
        ],
        "text": "\n".join(row.text for row in layout.texts),
    }
    monkeypatch.setattr(page_images, "read_document", lambda *_: local)
    return layout, local
