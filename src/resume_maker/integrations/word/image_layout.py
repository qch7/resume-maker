"""将图片空间识别结果转成可流动 Word，局部素材与文字分离，禁止整页背景伪装恢复。"""

import os
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import pymupdf
from docx.oxml.ns import qn
from docx.shared import Pt
from PIL import Image, ImageDraw

from resume_maker.core.errors import Problem
from resume_maker.integrations.providers.base import Cancelled
from resume_maker.integrations.word.pdf_assets import attach_asset
from resume_maker.integrations.word.pdf_flow import convert_flow, text_counter
from resume_maker.integrations.word.pdf_geometry import SOURCE
from resume_maker.integrations.word.pdf_recovery import LAYOUT_LOCK

FONT_NAMES = {
    "microsoft yahei": "微软雅黑",
    "microsoftyahei": "微软雅黑",
    "dengxian": "等线",
    "simhei": "黑体",
    "simsun": "宋体",
}


def validate_layout(layout):
    """拒绝相交的文字裁图和重复文字框，避免旧姓名、正文或整页混进素材。"""
    for asset in layout.assets:
        if asset.kind not in {"photo", "icon"}:
            continue
        box = pymupdf.Rect(asset.box)
        if box.get_area() > 0.4:
            raise Problem("照片或图标裁剪覆盖了过大页面区域，请只提供独立无正文素材。")
        for text in layout.texts:
            other = pymupdf.Rect(text.box)
            if (box & other).get_area() > other.get_area() * 0.02:
                raise Problem(f"{asset.kind} 裁剪框包含文字“{text.text[:30]}”，请分离图文。")
    for index, text in enumerate(layout.texts):
        box = pymupdf.Rect(text.box)
        for other in layout.texts[index + 1 :]:
            rect = pymupdf.Rect(other.box)
            if (box & rect).get_area() > min(box.get_area(), rect.get_area()) * 0.5:
                raise Problem(f"文字位置重叠：{text.text[:20]} / {other.text[:20]}。")


def page_size(image):
    """统一纸面短边，保持图片宽高比，不让截图 DPI 或像素数放大 Word 字号。"""
    scale = 595.276 / min(image.size)
    width, height = image.width * scale, image.height * scale
    if max(width, height) > 1584:
        raise Problem("图片过长，无法作为一张 Word 页面恢复，请按实际页面拆分图片。")
    return width, height


def font_for(text):
    """优先系统中匹配的常见字体；缺失时使用内置中文字体保证文字可编辑且不丢字。"""
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    families = {
        "等线": ("Deng.ttf", "Dengb.ttf"),
        "微软雅黑": ("msyh.ttc", "msyhbd.ttc"),
        "黑体": ("simhei.ttf", "simhei.ttf"),
        "宋体": ("simsun.ttc", "simsun.ttc"),
        "Arial": ("arial.ttf", "arialbd.ttf"),
        "Calibri": ("calibri.ttf", "calibrib.ttf"),
    }
    family = FONT_NAMES.get(text.font_name.lower(), text.font_name)
    names = families.get(family, families["等线"])
    path = fonts / names[int(text.bold)]
    return pymupdf.Font(fontfile=str(path)) if path.is_file() else pymupdf.Font("cjk")


def physical_box(box, width, height):
    """比例矩形转换为纸面点数，所有文字和素材共用同一坐标系。"""
    return pymupdf.Rect(box[0] * width, box[1] * height, box[2] * width, box[3] * height)


def color_rgb(color):
    """解析已校验的十六进制颜色，供矢量文字和重新绘制的底色共同使用。"""
    return tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))


def insert_texts(page, layout):
    """按图片文字框生成可编辑字符；字号依据字宽换算，不压缩字符或栅格化文字。"""
    fonts = {}
    for text in layout.texts:
        key = text.font_name, text.bold
        if key not in fonts:
            font = font_for(text)
            name = f"ImageFont{len(fonts)}"
            page.insert_font(fontname=name, fontbuffer=font.buffer)
            fonts[key] = name, font
        name, font = fonts[key]
        if any(not font.has_glyph(ord(char)) for char in text.text if not char.isspace()):
            raise Problem(f"当前字体缺少文字所需字符：{text.text[:35]}，请核对字体或图标分类。")
        box = physical_box(text.box, page.rect.width, page.rect.height)
        size = box.width / max(0.1, font.text_length(text.text, fontsize=1))
        # 比例框描述可见笔画；拒绝明显不像单行文字的框，不任意压扁字号来掩盖坏坐标。
        if not 0.45 * box.height <= size <= 2.5 * box.height or not 4 <= size <= 65:
            raise Problem(f"文字尺寸与行框不匹配：{text.text[:35]}，请重新识别紧密文字框。")
        ink_top = max(font.glyph_bbox(ord(char)).y1 for char in text.text if not char.isspace())
        baseline = box.y0 + ink_top * size
        page.insert_text(
            (box.x0, baseline),
            text.text,
            fontname=name,
            fontsize=size,
            color=tuple(value / 255 for value in color_rgb(text.color)),
        )


@contextmanager
def text_layer(layout, width, height):
    """构造临时几何页并核验全部识别字符，字体缺字或异常时及时关闭临时文档。"""
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=width, height=height)
        insert_texts(page, layout)
        expected = text_counter("".join(text.text for text in layout.texts))
        if expected - text_counter(page.get_text()):
            raise Problem("图片文字包含当前字体无法完整恢复的字符，请核对字体和原文后重试。")
        yield pdf


def asset_bytes(image, asset):
    """仅照片和图标从原图裁剪；底块与线条重新画，绝不包含原模板文字像素。"""
    box = physical_box(asset.box, image.width, image.height)
    if asset.kind in {"photo", "icon"}:
        result = image.crop(tuple(round(value) for value in box))
    else:
        result = Image.new("RGBA", (max(1, round(box.width)), max(1, round(box.height))))
        drawing = ImageDraw.Draw(result)
        if asset.polygon:
            points = [
                (x * image.width - box.x0, y * image.height - box.y0) for x, y in asset.polygon
            ]
            drawing.polygon(points, fill=asset.color)
        else:
            drawing.rectangle((0, 0, result.width, result.height), fill=asset.color)
    stream = BytesIO()
    result.save(stream, format="PNG")
    return stream.getvalue()


def place_image_assets(image, layout, paragraphs, width, height):
    """根据原始几何选择素材对应段落；底色、照片和图标各自保留用途及可伸展锚点。"""
    for asset in layout.assets:
        box = physical_box(asset.box, width, height)

        def distance(item, area=box, kind=asset.kind):
            """底块优先关联内部文字，其余素材优先同高度且横向最近的段落。"""
            _, rect, _ = item
            vertical = max(rect.y0 - area.y1, area.y0 - rect.y1, 0)
            horizontal = max(rect.x0 - area.x1, area.x0 - rect.x1, 0)
            if kind == "photo":
                # 照片按顶边关联；不能因靠近右侧学历/日期而被挂入它们的重复条目中。
                return abs(rect.y0 - area.y0), horizontal
            return vertical * 4 + horizontal * 0.15, abs(rect.y0 - area.y0)

        paragraph, rect, left = min(paragraphs, key=distance)
        layer = 0 if asset.kind == "background" else 2 if asset.kind == "photo" else 1
        attach_asset(
            paragraph,
            asset_bytes(image, asset),
            box,
            rect.y0,
            left,
            "图片模板：" + asset.kind,
            layer,
        )


def image_text_styles(paragraphs):
    """固定中文字体族并设置列表悬挂缩进，长内容换行后与正文对齐而非挤在圆点下面。"""
    for paragraph, _, _ in paragraphs:
        # 图片文字行的右边缘是原句末尾，不代表容器边缘；新资料可使用所在列的剩余宽度。
        paragraph.paragraph_format.right_indent = Pt(0)
        for run in paragraph.runs:
            family = FONT_NAMES.get((run.font.name or "").lower())
            if family:
                run.font.name = family
                run._r.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), family)
        if not paragraph.text.startswith("• "):
            continue
        run = next((run for run in paragraph.runs if run.text), None)
        if run is None or not run.text.startswith("• "):
            continue
        size = run.font.size.pt if run.font.size else 11
        style = paragraph.paragraph_format
        left = style.left_indent.pt if style.left_indent else 0
        hanging = size * 1.15
        style.left_indent = Pt(left + hanging)
        style.first_line_indent = Pt(-hanging)
        style.tab_stops.clear_all()
        style.tab_stops.add_tab_stop(Pt(left + hanging))
        run.text = "•\t" + run.text[2:]


def build_image_document(path, layout, flag):
    """串行调用具有全局状态的版面解析器，图片来源保留独立标记，不冒充原生 PDF。"""
    validate_layout(layout)
    with Image.open(path) as image:
        width, height = page_size(image)
        with text_layer(layout, width, height) as pdf:
            while not LAYOUT_LOCK.acquire(timeout=0.1):
                if flag.is_set():
                    raise Cancelled("图片模板恢复已取消。")
            try:
                if flag.is_set():
                    raise Cancelled("图片模板恢复已取消。")
                document, paragraphs = convert_flow(pdf[0], split_lines=True)
                document._element.set(SOURCE, "image-v1")
                image_text_styles(paragraphs)
                place_image_assets(image, layout, paragraphs, width, height)
                return document
            finally:
                LAYOUT_LOCK.release()
