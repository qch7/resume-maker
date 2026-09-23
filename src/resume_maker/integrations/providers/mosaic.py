"""在隐私出口生成低细节图片拼图，原件及元数据不进入模型附件"""

import hashlib
import re
from io import BytesIO

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from resume_maker.integrations.providers.base import Cancelled, ProviderError

MAX_IMAGES = 24
GRID_SIZE = 8
SHEET_SIZE = (640, 720)


def mosaic_tile(data):
    """压缩至最长边八个色块后放大，重新建立 RGB 图像以去除全部原始元数据"""
    if len(data) > 20 * 1024 * 1024:
        raise ProviderError("模板图片超过马赛克处理上限，已停止发送。")
    try:
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > 20_000_000:
                raise ProviderError("模板图片像素超过马赛克处理上限，已停止发送。")
            oriented = ImageOps.exif_transpose(source).convert("RGBA")
            flat = Image.new("RGB", oriented.size, "white")
            flat.paste(oriented, mask=oriented.getchannel("A"))
            scale = min(GRID_SIZE / max(flat.size), 0.25)
            grid = tuple(max(1, round(side * scale)) for side in flat.size)
            # 整张内嵌图片都打码，不能因人脸或文字检测漏检而留下原始局部
            tile = flat.resize(grid, Image.Resampling.BOX)
            scale = min(288 / flat.width, 188 / flat.height)
            size = tuple(max(1, round(side * scale)) for side in flat.size)
            return tile.resize(size, Image.Resampling.NEAREST)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ProviderError("模板图片无法安全打码，已停止发送，请人工确认图片用途。") from exc


def mosaic_sheets(images, cancelled):
    """逐张打码后添加固定节点编号，返回全新 PNG 附件及不含原件的审计摘要"""
    if len(images) > MAX_IMAGES or len({image.node for image in images}) != len(images):
        raise ProviderError("模板马赛克图片数量或节点编号无效。")
    if any(not re.fullmatch(r"n[1-9][0-9]{0,8}", image.node) for image in images):
        raise ProviderError("模板马赛克图片必须使用清单中的节点编号。")
    sheets, records = [], []
    for start in range(0, len(images), 6):
        sheet = Image.new("RGB", SHEET_SIZE, "white")
        draw = ImageDraw.Draw(sheet)
        batch = images[start : start + 6]
        for index, image in enumerate(batch):
            if cancelled.is_set():
                raise Cancelled("图片打码已取消。")
            tile = mosaic_tile(image.data)
            left, top = (index % 2) * 320, (index // 2) * 240
            draw.text((left + 16, top + 10), image.node, fill="black", font_size=18)
            sheet.paste(tile, (left + 160 - tile.width // 2, top + 36))
        output = BytesIO()
        sheet.save(output, format="PNG")
        data = output.getvalue()
        sheets.append(data)
        records.append(
            {
                "kind": "mosaic",
                "nodes": [image.node for image in batch],
                "grid_long_edge": GRID_SIZE,
                "width": sheet.width,
                "height": sheet.height,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return sheets, records
