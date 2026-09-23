"""验证扫描 PDF 的脱敏整页恢复、混合页面合并及重新识别时的隐私保护"""

import json
from io import BytesIO
from threading import Event

import pymupdf
import pytest
from docx import Document
from docx.oxml.ns import qn
from PIL import Image
from test_image_recovery import source_plan
from test_pdf_header_layout import header_content
from test_private_image_page import page_fixture
from test_template_analysis import simple_document

from resume_maker.core.errors import Problem
from resume_maker.domain.image_layout import ImagePage
from resume_maker.domain.models import ProviderSettings
from resume_maker.domain.templates import TemplatePlan
from resume_maker.integrations.local_ocr import OCRBudget
from resume_maker.integrations.providers import page_images
from resume_maker.integrations.providers.base import Cancelled, PageImage, ProviderError
from resume_maker.integrations.providers.codex import CodexProvider
from resume_maker.integrations.word.image.header import private_image_text
from resume_maker.integrations.word.pdf.geometry import SOURCE, recovered_pdf
from resume_maker.integrations.word.recovery import prepare_template
from resume_maker.integrations.word.templates.fill import fill_template
from resume_maker.integrations.word.templates.mapping import TemplatePackage
from resume_maker.services.templates.analysis import visual_evidence


def mixed_fixture(path, image):
    """合成两张不同尺寸扫描页和中间的原生文字页，隐藏文字层不得当作正文"""
    with pymupdf.open() as pdf:
        for index, (width, height) in enumerate([(500, 700), (400, 600), (420, 594)]):
            page = pdf.new_page(width=width, height=height)
            if index == 1:
                page.insert_text((40, 60), "NATIVE MIDDLE")
            else:
                page.insert_image(page.rect, filename=str(image), keep_proportion=False)
                page.insert_text((40, 400), "WRONG HIDDEN TEXT", render_mode=3)
        pdf.save(path)


def page_answer(payload, layout):
    """使用供应商实际收到的占位文字返回布局，禁止绕过网关本机还原"""
    context = json.loads(payload["input"].splitlines()[-1])
    result = layout.model_dump()
    for row, safe in zip(result["texts"], context["blocks"], strict=True):
        row.update(text=safe["text"], box=safe["box"])
    return result


def test_mixed_pdf_recovers_private_pages_and_reopens_safely(tmp_path, monkeypatch):
    """混合页保留尺寸、顺序和本机照片，重开任务仍逐页保护身份且不影响原生正文"""
    image, source, output = tmp_path / "image.png", tmp_path / "mixed.pdf", tmp_path / "result.docx"
    layout, local = page_fixture(image, monkeypatch)
    layout.texts[-1].text = "MYSTERY ID"
    layout.texts[-1].box = [0.1, 0.5, 0.3, 0.515]
    local["pages"][0]["blocks"][-1].update(
        text="MYSTERY ID", box=layout.texts[-1].box, confidence=0.4
    )
    local["text"] = "\n".join(row.text for row in layout.texts)
    mixed_fixture(source, image)
    original, calls = source.read_bytes(), []

    def runner(payload, *args, safe_images):
        """检查脱敏附件并模拟首次漏行后的有界重试"""
        calls.append(payload)
        assert len(safe_images) == 1
        assert payload["images"][0]["kind"] == "sanitized-page"
        assert "SAMPLE NAME" not in payload["input"]
        assert "MYSTERY ID" not in payload["input"]
        assert "WRONG HIDDEN TEXT" not in payload["input"]
        assert "NATIVE MIDDLE" not in payload["input"]
        with Image.open(BytesIO(safe_images[0])) as safe:
            assert max(safe.size) <= 1600 and not safe.info
            photo = next(a for a in layout.assets if a.kind == "photo")
            crop = safe.crop(page_images.pixel_box(photo.box, safe.size))
            assert len(crop.getcolors(crop.width * crop.height)) <= 100
        answer = page_answer(payload, layout)
        if len(calls) == 1:
            answer["texts"].pop()
        return json.dumps(answer)

    package, notes = prepare_template(
        source,
        output,
        CodexProvider(runner=runner),
        ProviderSettings(),
        Event(),
        lambda *_: None,
        simple_document(),
        [],
    )
    assert len(calls) == 3 and source.read_bytes() == original
    assert sum("脱敏整页" in note for note in notes) == 2
    document = Document(output)
    assert [(round(s.page_width.pt), round(s.page_height.pt)) for s in document.sections] == [
        (500, 700),
        (400, 600),
        (420, 594),
    ]
    text = "".join(node.text or "" for node in document._element.iter(qn("w:t")))
    assert text.count("SAMPLE NAME") == 2 and "WRONG HIDDEN TEXT" not in text
    assert text.index("SAMPLE NAME") < text.index("NATIVE MIDDLE") < text.rindex("SAMPLE NAME")
    assert "[[RM_" not in text and recovered_pdf(document._element)
    assert [s._sectPr.get(SOURCE) for s in document.sections] == ["image-v1", None, "image-v1"]
    media = [
        Image.open(BytesIO(rel.target_part.blob)).convert("RGB").tobytes()
        for rel in document.part.rels.values()
        if rel.reltype.endswith("/image")
    ]
    photo = next(a for a in layout.assets if a.kind == "photo")
    for number in (1, 3):
        with Image.open(tmp_path / f"recovery-page-{number}.png") as original_page:
            box = tuple(round(v * original_page.size[i % 2]) for i, v in enumerate(photo.box))
            assert original_page.crop(box).convert("RGB").tobytes() in media
    private = private_image_text(package)
    assert len(private["pages"]) == 2 and "NATIVE MIDDLE" not in private["text"]

    def reopened(payload, *args, **kwargs):
        """新的映射 Provider 必须重新登记每张扫描页的页首"""
        assert "OLD ROLE" not in payload["input"] and "SAMPLE NAME" not in payload["input"]
        assert "MYSTERY ID" not in payload["input"]
        assert "NATIVE MIDDLE" in payload["input"]
        return TemplatePlan(
            summary="checked",
            fields=[],
            repeats=[],
            photos=[],
            keep=[],
            remove=[],
            warnings=[],
        ).model_dump_json()

    provider = CodexProvider(runner=reopened)
    visual_evidence(provider, package, output, tmp_path, Event())
    provider.run_structured(
        result_model=TemplatePlan,
        workspace=tmp_path,
        prompt=text,
        thread_id=None,
        settings=ProviderSettings(),
        cancelled=Event(),
        emit=lambda *_: None,
    )


@pytest.mark.parametrize("failure", ["model", "ocr", "cancel"])
def test_pdf_later_page_failure_keeps_previous_output(tmp_path, monkeypatch, failure):
    """后续扫描页失败或迟到取消时保留已有结果，原 PDF 始终不修改"""
    image, source, output = tmp_path / "image.png", tmp_path / "mixed.pdf", tmp_path / "result.docx"
    layout, local = page_fixture(image, monkeypatch)
    mixed_fixture(source, image)
    original = source.read_bytes()
    output.write_bytes(b"previous result")
    flag, calls = Event(), []

    def ocr(path, cancelled):
        """只让后续页的本机处理失败，确认不会发送原图补救"""
        if path.name == "recovery-page-3.png" and failure == "ocr":
            raise ProviderError("OCR unavailable")
        return local

    def runner(payload, *args, safe_images):
        """首张扫描页成功，后续页模拟失败或结果返回后的取消"""
        calls.append(payload)
        if len(calls) > 1:
            if failure == "model":
                raise ProviderError("model unavailable")
            if failure == "cancel":
                flag.set()
        return json.dumps(page_answer(payload, layout))

    monkeypatch.setattr(page_images, "read_document", ocr)
    with pytest.raises(Cancelled if failure == "cancel" else Problem):
        prepare_template(
            source,
            output,
            CodexProvider(runner=runner),
            ProviderSettings(),
            flag,
            lambda *_: None,
            simple_document(),
            [],
        )
    assert len(calls) == {"model": 3, "ocr": 1, "cancel": 2}[failure]
    assert output.read_bytes() == b"previous result" and source.read_bytes() == original


@pytest.mark.parametrize("limit", ["pages", "characters", "blocks"])
def test_pdf_ocr_budget_stops_request_before_send(tmp_path, monkeypatch, limit):
    """跨页额度触顶时请求止于隐私出口，同页重试不重复占用页数"""
    source = tmp_path / "image.png"
    layout, _ = page_fixture(source, monkeypatch)
    budget = OCRBudget()
    for i in range(11):
        budget.register(i, [])
    calls = []

    def runner(payload, *args, **kwargs):
        """计数实际抵达供应商的请求"""
        calls.append(payload)
        return json.dumps(page_answer(payload, layout))

    provider = CodexProvider(runner=runner)

    def request():
        """让当前页经过真实隐私出口进行累计限额检查"""
        return provider.run_structured(
            result_model=ImagePage,
            workspace=tmp_path,
            prompt="恢复扫描页",
            thread_id=None,
            settings=ProviderSettings(),
            cancelled=Event(),
            emit=lambda *_: None,
            images=[PageImage(source, budget)],
        )

    request()
    request()
    assert len(calls) == 2 and len(budget.pages) == 12
    if limit == "pages":
        budget.pages["another-page"] = (0, 0)
    elif limit == "characters":
        budget.pages[0] = (100000, 0)
    else:
        budget.pages[0] = (0, 6000)
    with pytest.raises(ProviderError, match="超过"):
        request()
    assert len(calls) == 2


def test_native_conversion_failure_uses_sanitized_page(tmp_path, monkeypatch):
    """原生转换器失败的页面也使用脱敏整页重建，保留失败原因"""
    image, source, output = (
        tmp_path / "image.png",
        tmp_path / "native.pdf",
        tmp_path / "result.docx",
    )
    layout, _ = page_fixture(image, monkeypatch)
    with pymupdf.open() as pdf:
        pdf.new_page(width=595, height=842).insert_text((40, 60), "Native conversion problem")
        pdf.save(source)

    def fail(*args):
        """仅替换原生入口，图片几何转换仍执行真实解析器"""
        raise ValueError("unsupported native geometry")

    monkeypatch.setattr("resume_maker.integrations.word.pdf.recovery.convert_flow", fail)
    calls = []

    def runner(payload, *args, safe_images):
        """转换失败也不允许原始页面直发"""
        calls.append(payload)
        assert len(safe_images) == 1 and payload["images"][0]["kind"] == "sanitized-page"
        return json.dumps(page_answer(payload, layout))

    package, notes = prepare_template(
        source,
        output,
        CodexProvider(runner=runner),
        ProviderSettings(),
        Event(),
        lambda *_: None,
        simple_document(),
        [],
    )
    assert len(calls) == 1 and any("unsupported native geometry" in note for note in notes)
    assert "SAMPLE NAME" in private_image_text(package)["text"]


def test_private_pdf_keeps_empty_pages_without_ocr(tmp_path, monkeypatch):
    """真正空白的 PDF 页只保留纸张和分节，不触发 OCR 或模型请求"""
    source, output = tmp_path / "blank-middle.pdf", tmp_path / "result.docx"
    with pymupdf.open() as pdf:
        pdf.new_page(width=400, height=500).insert_text((40, 60), "FIRST PAGE")
        pdf.new_page(width=300, height=400)
        pdf.new_page(width=500, height=600).insert_text((40, 60), "FINAL PAGE")
        pdf.save(source)

    def forbidden(*args, **kwargs):
        """原生文字和空白页面无需启动图像识别"""
        pytest.fail("原生和空白 PDF 页不应 OCR 或调用模型")

    monkeypatch.setattr(page_images, "read_document", forbidden)
    _, notes = prepare_template(
        source,
        output,
        CodexProvider(runner=forbidden),
        ProviderSettings(),
        Event(),
        lambda *_: None,
        simple_document(),
        [],
    )
    assert [
        (round(s.page_width.pt), round(s.page_height.pt)) for s in Document(output).sections
    ] == [
        (400, 500),
        (300, 400),
        (500, 600),
    ]
    assert any("空白页" in note for note in notes)
    assert not any("视觉识别" in note for note in notes)


def test_scanned_pdf_fields_and_photo_remain_fillable(tmp_path, monkeypatch):
    """扫描页恢复后沿用模板填充，替换姓名联系方式和照片并清除旧隐私元数据"""
    image, source, output = tmp_path / "image.png", tmp_path / "scan.pdf", tmp_path / "result.docx"
    layout, _ = page_fixture(image, monkeypatch)
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_image(page.rect, filename=str(image))
        pdf.save(source)

    def runner(payload, *args, safe_images):
        """返回已通过隐私网关的布局"""
        return json.dumps(page_answer(payload, layout))

    package, _ = prepare_template(
        source,
        output,
        CodexProvider(runner=runner),
        ProviderSettings(),
        Event(),
        lambda *_: None,
        simple_document(),
        [],
    )
    plan = source_plan(package)
    assert len(plan.photos) == 1
    filled = tmp_path / "filled.docx"
    notices = fill_template(output, filled, plan, header_content().model_dump(), [])
    result = TemplatePackage(filled)
    root = result.parts["word/document.xml"]
    text = "".join(node.text or "" for node in root.iter(qn("w:t")))
    assert "NEW NAME" in text and "SAMPLE NAME" not in text and "OLD PHONE" not in text
    assert any("重排 PDF 顶部" in note for note in notices)
    assert not any(
        key.startswith("{urn:resume-maker:pdf}") for node in root.iter() for key in node.attrib
    )
