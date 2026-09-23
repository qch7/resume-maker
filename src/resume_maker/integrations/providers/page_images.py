"""以本地 OCR 和粗色块重绘整页证据，原始文字像素及照片细节不进入附件"""

import hashlib
import math
import re
from collections import Counter
from io import BytesIO

import pymupdf
from PIL import Image, ImageDraw, ImageFont, ImageOps

from resume_maker.integrations.local_ocr import REVIEW_SCORE, check_cancelled, read_document
from resume_maker.integrations.providers.base import ProviderError
from resume_maker.integrations.providers.mosaic import GRID_SIZE

PAGE_INSTRUCTIONS = """附件是本机脱敏重绘的整页布局，所有图像区域都已打码，文字来自本地 OCR。
敏感文字用不透明色块覆盖，T 编号对应 blocks 中的行；不要猜测或抄录色块编号。
texts 必须逐行使用 blocks 的 text 和 box，每行恰好一次，不得遗漏、改写、合并或拆分。
box 是原文字框，不是占位符显示宽度；字符长度见 characters，字体只能估计。
保留 text 中完整的隐私占位符，本机负责恢复原文。凭据移除标记不得改写。
graphics 给出本机找到的打码区域，其边框仅供参考，可能包含多个元素或复杂背景。
结合整页位置判断照片、图标和装饰的用途，不能把文字色块当成图片素材。
不要因为马赛克缺少细节就遗漏照片；不确定之处写入 notes。
"""
SECTION_HEADING = re.compile(
    r"^(?:个人简介|自我评价|专业技能|职业技能|技能特长|工作经[历验]|实习经[历验]|"
    r"项目经[历验]|教育(?:经历|背景)|获奖(?:经历|荣誉)|荣誉奖项|"
    r"profile|summary|skills|experience|work experience|education|projects|awards)$",
    re.IGNORECASE,
)


def protect_header(blocks, redactor):
    """页首身份区整体保护，避免未登记姓名和 OCR 误认的联系方式漏过格式规则"""
    boundary = min(
        (row["box"][1] for row in blocks if SECTION_HEADING.fullmatch(row["text"].strip())),
        default=0.25,
    )
    redactor.values.update(row["text"] for row in blocks if row["box"][1] < min(boundary, 0.25))


def validate_page_text(result, context):
    """阻止模型遗漏、改写或猜测被遮盖的 OCR 原文"""
    if not isinstance(result, dict) or not isinstance(result.get("texts"), list):
        raise ProviderError("图片恢复结果缺少 OCR 文字行。")
    expected = Counter(row["text"] for row in context["blocks"])
    actual = Counter(
        row["text"]
        for row in result["texts"]
        if isinstance(row, dict) and isinstance(row.get("text"), str)
    )
    if expected != actual:
        raise ProviderError("图片恢复结果未完整保留本地 OCR 行，请逐行复制原文及占位符。")
    expected_boxes = Counter(
        (row["text"], tuple(round(v, 4) for v in row["box"])) for row in context["blocks"]
    )
    try:
        actual_boxes = Counter(
            (row["text"], tuple(round(v, 4) for v in row["box"])) for row in result["texts"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderError("图片恢复结果缺少有效的 OCR 行坐标。") from exc
    if expected_boxes != actual_boxes:
        raise ProviderError("图片恢复结果改变了本地 OCR 行坐标，请完整复制原框。")


def pixel_box(box, size, padding=0):
    """将比例框向外取整并限制在当前图片内，覆盖边缘抗锯齿像素"""
    width, height = size
    return (
        max(0, math.floor(box[0] * width) - padding),
        max(0, math.floor(box[1] * height) - padding),
        min(width, math.ceil(box[2] * width) + padding),
        min(height, math.ceil(box[3] * height) + padding),
    )


def common_color(image):
    """用量化后的主色估计底色，不携带原图纹理"""
    sample = image.copy()
    sample.thumbnail((160, 160))
    colors = sample.quantize(colors=8).convert("RGB").getcolors(25600)
    return max(colors, key=lambda item: item[0])[1]


def row_colors(image, box):
    """估计单行文字和底色以保留深底白字等版面关系"""
    crop = image.crop(pixel_box(box, image.size))
    # OCR 框内的密集笔画可能比底色多，使用框外边缘估计底色
    area = pixel_box(box, image.size, 3)
    outer = image.crop(area)
    border = Image.new("RGB", (outer.width * 2 + outer.height * 2, 1))
    offset = 0
    for strip in (
        outer.crop((0, 0, outer.width, 1)),
        outer.crop((0, outer.height - 1, outer.width, outer.height)),
        outer.crop((0, 0, 1, outer.height)).transpose(Image.Transpose.ROTATE_90),
        outer.crop((outer.width - 1, 0, outer.width, outer.height)).transpose(
            Image.Transpose.ROTATE_90
        ),
    ):
        border.paste(strip, (offset, 0))
        offset += strip.width
    background = common_color(border)
    colors = crop.quantize(colors=4).convert("RGB").getcolors(crop.width * crop.height)
    foreground = max(
        colors,
        key=lambda item: sum((a - b) ** 2 for a, b in zip(item[1], background, strict=True)),
    )[1]
    return background, foreground


def graphic_regions(image, background):
    """合并相邻非文字色块，保留位置并对整个区域使用最多八格的马赛克"""
    import cv2
    import numpy as np

    pixels = np.asarray(image).astype(np.int16)
    mask = (np.max(np.abs(pixels - background), axis=2) > 35).astype(np.uint8) * 255
    radius = max(2, round(min(image.size) * 0.008))
    kernel = np.ones((radius * 2 + 1, radius * 2 + 1), dtype=np.uint8)
    # 合并头像内部及邻近碎片，不能将眼鼻等局部各自当成独立图片保留细节
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    count, _, stats, _ = cv2.connectedComponentsWithStats(closed)
    regions = []
    for x, y, width, height, area in stats[1:count]:
        if area < 8:
            continue
        regions.append((int(x), int(y), int(x + width), int(y + height)))
    if len(regions) > 600:
        raise ProviderError("页面图形过于复杂，无法可靠生成脱敏版面，请换用清晰模板。")
    # 外框可能包围未连接的内部图案，统一合并后打码以免细节被重复贴回
    merged = []
    for box in sorted(regions, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True):
        index = 0
        while index < len(merged):
            other = merged[index]
            if (
                box[0] <= other[2] + radius
                and box[2] + radius >= other[0]
                and box[1] <= other[3] + radius
                and box[3] + radius >= other[1]
            ):
                box = (
                    min(box[0], other[0]),
                    min(box[1], other[1]),
                    max(box[2], other[2]),
                    max(box[3], other[3]),
                )
                merged.pop(index)
                index = 0
            else:
                index += 1
        merged.append(box)
    return merged


def draw_row(canvas, row, color, private, font):
    """安全文字重新绘制，敏感行只显示不含原文的遮盖及编号"""
    box = pixel_box(row["box"], canvas.size)
    width, height = max(1, box[2] - box[0]), max(1, box[3] - box[1])
    if private:
        draw = ImageDraw.Draw(canvas)
        draw.rectangle(box, fill="#535965")
        draw.text((box[0] + 1, box[1]), row["id"], fill="white", font_size=max(8, height - 2))
        return
    bounds = font.getbbox(row["text"])
    tile = Image.new("RGBA", (max(1, bounds[2] - bounds[0]), max(1, bounds[3] - bounds[1])))
    ImageDraw.Draw(tile).text((-bounds[0], -bounds[1]), row["text"], font=font, fill=color)
    tile = tile.resize((width, height), Image.Resampling.LANCZOS)
    canvas.paste(tile, box[:2], tile)


def sanitized_page(path, redactor, cancelled):
    """先学习完整 OCR 再生成全新页面，任何阶段失败都不能回退原图"""
    check_cancelled(cancelled)
    document = read_document(path, cancelled)
    if len(document["pages"]) != 1 or not document["pages"][0]["blocks"]:
        raise ProviderError("图片模板必须包含一页可识别文字，无法脱敏时已停止发送。")
    blocks = document["pages"][0]["blocks"]
    if len(blocks) > 1500:
        raise ProviderError("图片文字行数超过版面恢复上限，请拆分页面。")
    redactor.learn(document["text"])
    protect_header(blocks, redactor)
    redactor.values.update(row["text"] for row in blocks if row["confidence"] < REVIEW_SCORE)
    rows, colors, private = [], [], []
    with Image.open(path) as source:
        if getattr(source, "n_frames", 1) != 1:
            raise ProviderError("多帧图片无法作为单页脱敏，请拆分页面。")
        oriented = ImageOps.exif_transpose(source).convert("RGBA")
        image = Image.new("RGB", oriented.size, "white")
        image.paste(oriented, mask=oriented.getchannel("A"))
    image.thumbnail((1600, 1600))
    cleared = image.copy()
    drawing = ImageDraw.Draw(cleared)
    for index, block in enumerate(blocks):
        check_cancelled(cancelled)
        safe_text = redactor.text(block["text"])
        background, foreground = row_colors(image, block["box"])
        # 所有 OCR 文字都移除后重绘，防止照片或相邻漏识别字符借文字裁图出网
        padding = max(3, round((block["box"][3] - block["box"][1]) * image.height * 0.2))
        drawing.rectangle(pixel_box(block["box"], image.size, padding), fill=background)
        rows.append(
            {
                "id": f"T{index + 1}",
                "text": safe_text,
                "box": block["box"],
                "characters": len(block["text"]),
                "color": "#" + "".join(f"{value:02X}" for value in foreground),
            }
        )
        colors.append((background, foreground))
        private.append(safe_text != block["text"])
    background = common_color(cleared)
    canvas = Image.new("RGB", image.size, background)
    graphics = []
    for box in graphic_regions(cleared, background):
        check_cancelled(cancelled)
        tile = cleared.crop(box)
        scale = min(GRID_SIZE / max(tile.size), 0.25)
        grid = tuple(max(1, round(side * scale)) for side in tile.size)
        tile = tile.resize(grid, Image.Resampling.BOX).resize(tile.size, Image.Resampling.NEAREST)
        canvas.paste(tile, box[:2])
        graphics.append([round(v / image.size[i % 2], 6) for i, v in enumerate(box)])
    font = ImageFont.truetype(BytesIO(pymupdf.Font("cjk").buffer), size=40)
    for row, (background, foreground), hidden in zip(rows, colors, private, strict=True):
        check_cancelled(cancelled)
        ImageDraw.Draw(canvas).rectangle(pixel_box(row["box"], canvas.size, 1), fill=background)
        draw_row(canvas, row, foreground, hidden, font)
    output = BytesIO()
    canvas.save(output, format="PNG")
    data = output.getvalue()
    context = {"blocks": rows, "graphics": graphics}
    audit = {
        "kind": "sanitized-page",
        "width": canvas.width,
        "height": canvas.height,
        "text_rows": len(rows),
        "covered_rows": sum(private),
        "graphic_regions": len(graphics),
        "grid_long_edge": GRID_SIZE,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    check_cancelled(cancelled)
    return data, context, audit
