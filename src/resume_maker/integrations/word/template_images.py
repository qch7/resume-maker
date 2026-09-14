"""把模板内图片组成带节点标识的缩略图，供 AI 判断照片与装饰用途。"""

from pathlib import Path

import pymupdf

from resume_maker.core.errors import Problem


def image_sheets(package, directory: Path) -> tuple[list[Path], list[str]]:
    """只读取包内图片，最多展示二十四张；无法解码的图片继续由文字清单报告。"""
    images, shown = [], []
    for row in package.inventory()["nodes"]:
        if row["kind"] != "image" or len(images) >= 24:
            continue
        try:
            raw = package.image(row["id"])
            pixmap = pymupdf.Pixmap(raw)
            if pixmap.width * pixmap.height > 20_000_000:
                continue
            images.append((row["id"], raw))
            shown.append(row["id"])
        except (Problem, RuntimeError, ValueError):
            continue
    paths = []
    for start in range(0, len(images), 6):
        with pymupdf.open() as document:
            page = document.new_page(width=640, height=720)
            for index, (identifier, raw) in enumerate(images[start : start + 6]):
                left, top = (index % 2) * 320, (index // 2) * 240
                page.insert_text((left + 16, top + 24), identifier, fontsize=14)
                page.insert_image(
                    pymupdf.Rect(left + 16, top + 36, left + 304, top + 224), stream=raw
                )
            output = directory / f"images-{start // 6 + 1}.png"
            page.get_pixmap().save(output)
            paths.append(output)
    return paths, shown
