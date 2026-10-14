"""验证本地文档分流、资源限制、OCR 识别、进入模型前的脱敏"""

import json
import threading
from pathlib import Path

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from resume_maker.domain.models import Model, ProviderSettings
from resume_maker.plugin_packages.provider_rapidocr import local_ocr
from resume_maker.sdk.model import Cancelled, ProviderError
from tests.support.providers import privacy_provider


def test_native_pdf_avoids_ocr(tmp_path, monkeypatch):
    """可靠文字层直接提取，避免 OCR 开销及文字误认"""
    path = tmp_path / "native.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), "Recipient: Alice Example\nAward 2026")
        pdf.save(path)

    def forbidden():
        """纯文字 PDF 不得加载 OCR 模型"""
        pytest.fail("不应加载 OCR")

    monkeypatch.setattr(local_ocr, "engine", forbidden)
    result = local_ocr.read_document(path, threading.Event())
    assert "Alice Example" in result["text"]
    assert result["pages"][0]["method"] == "pdf-text"


def test_retry_recovers_small_text_and_composites_alpha(monkeypatch):
    """高置信度稀疏结果仍触发复核，透明底先合成为白色"""
    sizes = []

    def reader(pixels):
        """模拟初次漏掉小字且复核恢复两行的情况"""
        sizes.append(pixels.shape)
        assert (pixels[0, 0] == 255).all()
        height, width = pixels.shape[:2]
        rows = [
            [
                [[0, 0], [width * 0.3, 0], [width * 0.3, height * 0.04], [0, height * 0.04]],
                "Title",
                0.99,
            ]
        ]
        if len(sizes) == 2:
            rows.append(
                [
                    [
                        [0, height * 0.1],
                        [width * 0.3, height * 0.1],
                        [width * 0.3, height * 0.13],
                        [0, height * 0.13],
                    ],
                    "small text",
                    0.98,
                ]
            )
        return rows, []

    monkeypatch.setattr(local_ocr, "engine", lambda: reader)
    result = local_ocr.recognize(Image.new("RGBA", (1600, 2400)), threading.Event())
    assert len(sizes) == 2 and sizes[1][0] > sizes[0][0]
    assert result["blocks"][1]["text"] == "small text"


def retry_result(monkeypatch, previous, alternate):
    """把归一化合成文字框转换到每轮真实图片尺寸后执行完整复核流程"""
    calls = []

    def reader(pixels):
        """两轮返回同一纸面坐标中的可控文字，不加载识别模型"""
        blocks = previous if not calls else alternate
        calls.append(pixels.shape)
        height, width = pixels.shape[:2]
        return [
            [
                [
                    [x0 * width, y0 * height],
                    [x1 * width, y0 * height],
                    [x1 * width, y1 * height],
                    [x0 * width, y1 * height],
                ],
                text,
                score,
            ]
            for text, (x0, y0, x1, y1), score in blocks
        ], []

    monkeypatch.setattr(local_ocr, "engine", lambda: reader)
    result = local_ocr.recognize(Image.new("RGB", (1600, 2400), "white"), threading.Event())
    assert len(calls) == 2
    return result["blocks"]


def test_retry_preserves_missing_text_and_adds_disjoint_regions(monkeypatch):
    """新增高分短行不能挤掉首次长正文，低分新区域不参与保守补充"""
    previous = [("Original important paragraph", (0.1, 0.1, 0.9, 0.2), 0.96)]
    alternate = [
        ("new heading", (0.1, 0.3, 0.5, 0.4), 0.99),
        ("new date", (0.1, 0.5, 0.5, 0.6), 0.99),
        ("uncertain", (0.1, 0.7, 0.5, 0.8), 0.4),
    ]
    blocks = retry_result(monkeypatch, previous, alternate)
    assert [block["text"] for block in blocks] == [
        "Original important paragraph",
        "new heading",
        "new date",
    ]
    assert blocks[0]["box"] == pytest.approx(previous[0][1])


@pytest.mark.parametrize("split", [True, False])
def test_retry_accepts_split_or_merged_rows(monkeypatch, split):
    """空间覆盖及文字一致时允许拆行或合行，结果数量不决定是否采用"""
    whole = [("First Second", (0.1, 0.1, 0.9, 0.2), 0.96)]
    parts = [
        ("First", (0.1, 0.1, 0.5, 0.2), 0.98),
        ("Second", (0.5, 0.1, 0.9, 0.2), 0.98),
    ]
    previous, alternate = (whole, parts) if split else (parts, whole)
    blocks = retry_result(monkeypatch, previous, alternate)
    assert [block["text"] for block in blocks] == [row[0] for row in alternate]


@pytest.mark.parametrize("case", ["partial", "different", "confidence"])
def test_retry_rejects_incomplete_or_worse_region(monkeypatch, case):
    """重复框不能累加覆盖面积，同位置无关文字或低分结果不得覆盖可靠原文"""
    previous = [("Reliable original text", (0.1, 0.1, 0.9, 0.2), 0.99)]
    alternate = {
        "partial": [("Reliable original text", (0.1, 0.1, 0.5, 0.2), 0.99)] * 3,
        "different": [("Something else", (0.1, 0.1, 0.9, 0.2), 0.99)],
        "confidence": [("Reliable original text", (0.1, 0.1, 0.9, 0.2), 0.7)],
    }[case]
    blocks = retry_result(monkeypatch, previous, alternate)
    assert len(blocks) == 1 and blocks[0]["text"] == previous[0][0]
    assert blocks[0]["box"] == pytest.approx(previous[0][1])
    assert blocks[0]["confidence"] == previous[0][2]


def test_retry_can_correct_uncertain_text_in_same_region(monkeypatch):
    """低分旧行有完整空间对应时允许复核纠正文字"""
    previous = [("uncertain", (0.1, 0.1, 0.9, 0.2), 0.4)]
    alternate = [("Recovered text", (0.1, 0.1, 0.9, 0.2), 0.99)]
    blocks = retry_result(monkeypatch, previous, alternate)
    assert [block["text"] for block in blocks] == ["Recovered text"]


def test_retry_neighbor_cannot_hide_degraded_line_confidence(monkeypatch):
    """擦边的长高分邻行不能掩盖原文字区域内置信度明显下降"""
    previous = [("Reliable original text", (0.1, 0.1, 0.9, 0.2), 0.99)]
    alternate = [
        ("Reliable original text", (0.1, 0.1, 0.9, 0.2), 0.1),
        ("Neighbor " * 120, (0.899, 0.1, 1, 0.2), 0.99),
    ]
    blocks = retry_result(monkeypatch, previous, alternate)
    assert len(blocks) == 1 and blocks[0]["text"] == previous[0][0]
    assert blocks[0]["confidence"] == 0.99


def test_retry_merged_line_cannot_drop_digit_from_reliable_text(monkeypatch):
    """合行虽覆盖原区域，也不能丢弃已有高置信号码中的任意一位"""
    previous = [
        ("Phone 13800138000", (0.1, 0.1, 0.9, 0.2), 0.99),
        ("School", (0.1, 0.2, 0.9, 0.3), 0.99),
    ]
    alternate = [("Phone 1380013800 School", (0.1, 0.1, 0.9, 0.3), 0.99)]
    blocks = retry_result(monkeypatch, previous, alternate)
    assert [block["text"] for block in blocks] == [row[0] for row in previous]


def test_document_limits_and_cancel(tmp_path):
    """页数限制、已取消请求在识别之前停止"""
    path = tmp_path / "long.pdf"
    with pymupdf.open() as pdf:
        for _ in range(local_ocr.MAX_PAGES + 1):
            pdf.new_page()
        pdf.save(path)
    with pytest.raises(ProviderError, match="1–12"):
        local_ocr.read_document(path, threading.Event())
    flag = threading.Event()
    flag.set()
    with pytest.raises(Cancelled):
        local_ocr.read_document(path, flag)


def test_hidden_pdf_text_not_trusted(monkeypatch):
    """隐藏旧 OCR 层不能覆盖本次从可见像素提取的文字"""
    monkeypatch.setattr(
        local_ocr,
        "recognize",
        lambda *_: {
            "width": 100,
            "height": 100,
            "method": "ocr",
            "blocks": [{"text": "Visible text", "box": [0.1, 0.1, 0.4, 0.2], "confidence": 0.99}],
        },
    )
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), "Incorrect hidden text", render_mode=3)
        result = local_ocr.pdf_page(page, threading.Event())
    assert [row["text"] for row in result["blocks"]] == ["Visible text"]


def test_actual_ocr_private_fields_never_reach_runner(tmp_path):
    """真实 CPU OCR 提取图片、扫描 PDF，姓名电话在 CLI 材料中只保留占位符"""
    font_file = next(
        (
            p
            for p in (
                Path("C:/Windows/Fonts/arial.ttf"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            )
            if p.exists()
        ),
        None,
    )
    if font_file is None:
        pytest.skip("需要系统测试字体")
    image = Image.new("RGB", (1000, 700), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_file), 40)
    for i, text in enumerate(("AWARD CERTIFICATE", "Name: Alice Example", "Phone: 13800138000")):
        draw.text((70, 80 + 160 * i), text, fill="black", font=font)
    path = tmp_path / "certificate.png"
    image.save(path)
    local = local_ocr.read_document(path, threading.Event())
    assert "Alice Example" in local["text"] and "13800138000" in local["text"]
    pdf_path = tmp_path / "scan.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=500, height=350)
        page.insert_image(page.rect, filename=str(path))
        pdf.save(pdf_path)
    assert "13800138000" in local_ocr.read_document(pdf_path, threading.Event())["text"]

    class Answer(Model):
        """用于验证图片资料经过网关的最小契约"""

        answer: str

    captured = []

    def runner(payload, *_):
        """只记录脱敏包，供应商调用始终由本地替身接管"""
        captured.append(payload)
        return '{"answer":"done"}'

    result = privacy_provider(runner=runner).run_structured(
        result_model=Answer,
        workspace=tmp_path,
        prompt="Extract the award",
        thread_id=None,
        settings=ProviderSettings(),
        cancelled=threading.Event(),
        emit=lambda *_: None,
        images=[path],
    )
    assert result.answer == "done"
    serialized = json.dumps(captured)
    assert "Alice Example" not in serialized and "13800138000" not in serialized
    assert "[[RM_" in serialized and "input_image" not in serialized


def test_uncertain_ocr_span_masked_whole(tmp_path, monkeypatch):
    """低分文字即使没有姓名标签，也在发送前整体替换"""

    document = {
        "text": "UncertainPerson",
        "pages": [
            {"blocks": [{"text": "UncertainPerson", "confidence": 0.4, "box": [0, 0, 1, 1]}]}
        ],
    }
    monkeypatch.setattr(local_ocr, "read_document", lambda *_: document)

    class Answer(Model):
        """检验低置信度文字处理的最小响应"""

        answer: str

    def runner(payload, *_):
        """不依赖姓名规则，检查整段不确定原文已经替换"""
        assert "UncertainPerson" not in json.dumps(payload)
        return '{"answer":"done"}'

    privacy_provider(runner=runner).run_structured(
        result_model=Answer,
        workspace=tmp_path,
        prompt="Analyze",
        thread_id=None,
        settings=ProviderSettings(),
        cancelled=threading.Event(),
        emit=lambda *_: None,
        images=[tmp_path / "local.png"],
    )
