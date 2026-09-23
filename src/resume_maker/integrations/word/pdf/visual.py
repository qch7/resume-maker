"""扫描 PDF 页通过统一隐私出口恢复版面，原文和照片只在本机还原"""

import pymupdf

from resume_maker.core.errors import Problem
from resume_maker.integrations.providers.base import Cancelled
from resume_maker.integrations.word.image.layout import build_image_document
from resume_maker.integrations.word.image.recovery import recognize_image
from resume_maker.integrations.word.ooxml import w
from resume_maker.integrations.word.pdf.flow import append_document
from resume_maker.integrations.word.pdf.geometry import PRIVATE


def recover_private_page(document, page, number, output, provider, settings, flag, emit, budget):
    """按规范化后的页面渲染并恢复，保留实际尺寸和每页隐私标记"""
    image = output.parent / f"recovery-page-{number}.png"
    size = page.rect.width, page.rect.height
    scale = min(3, 2400 / max(size))
    page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(image)
    emit("activity", {"type": "prepare", "text": f"正在脱敏并恢复 PDF 第 {number} 页版面"})
    try:
        recovered = recognize_image(
            provider, image, output, settings, flag, emit, paper_size=size, budget=budget
        )
        (output.parent / f"pdf-layout-{number}.json").write_text(
            recovered.model_dump_json(), encoding="utf-8"
        )
        restored = build_image_document(image, recovered, flag, paper_size=size)
    except Cancelled:
        raise
    except Exception as exc:
        raise Problem(f"PDF 第 {number} 页版面恢复失败：{exc}") from exc
    if flag.is_set():
        raise Cancelled("模板自动整理已取消。")
    # 保留页首以外的不确定 OCR 身份，重新打开任务时仍须整段遮盖
    for node in restored._element.iter(w("p")):
        text = "".join(part.text or "" for part in node.iter(w("t")))
        if any(value and value in text for value in getattr(provider, "sensitive_values", ())):
            node.set(PRIVATE, "1")
    append_document(document, restored)
    return [
        f"第 {number} 页已本地 OCR 并遮盖敏感文字、打码图像，AI 根据脱敏整页恢复版面；"
        "原文和照片已在本机还原，OCR、字体和复杂装饰需核对。",
        *[f"第 {number} 页：{note}" for note in recovered.notes],
    ]
