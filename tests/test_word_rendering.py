"""验证矢量分页独立于本机字体和缩放，并保留现有图片输出。"""

import pymupdf
from lxml import etree

from resume_maker.integrations.word.rendering import render_pages


def test_vector_pages_preserve_page_sizes_and_outline_text(tmp_path):
    """不同尺寸的 PDF 页面生成矢量轮廓，避免字体替换且不把文字栅格化。"""
    pdf = tmp_path / "resume.pdf"
    with pymupdf.open() as document:
        for width, height in [(595, 842), (842, 595)]:
            page = document.new_page(width=width, height=height)
            page.insert_text((40, 50), "Resume preview", fontsize=12)
            page.draw_line((40, 60), (width - 40, 60))
        document.save(pdf)
    assert render_pages(pdf) == 2
    ns = {"svg": "http://www.w3.org/2000/svg"}
    for index, (width, height) in enumerate([(595, 842), (842, 595)], 1):
        root = etree.parse(str(tmp_path / f"page-{index}.svg")).getroot()
        assert root.get("viewBox") == f"0 0 {width} {height}"
        assert root.findall(".//svg:path", ns)
        assert not root.findall(".//svg:text", ns)
        assert not root.findall(".//svg:image", ns)
        assert (tmp_path / f"page-{index}.png").is_file()
