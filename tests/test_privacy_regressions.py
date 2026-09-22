"""验证隐私出口保留原有源码分析和原生 PDF 解析能力"""

import json
import threading
from io import BytesIO
from typing import Literal

import pymupdf
import pytest
from docx import Document
from PIL import Image
from test_privacy import provider_at, reply, run
from test_template_analysis import simple_document

from resume_maker.domain.models import Model, ProviderSettings
from resume_maker.integrations import local_ocr
from resume_maker.integrations.privacy import TOKEN
from resume_maker.integrations.providers.codex import CodexProvider
from resume_maker.integrations.providers.material_server import call
from resume_maker.integrations.providers.sandbox import materials
from resume_maker.integrations.source_context import source_context
from resume_maker.integrations.word.recovery import prepare_template


@pytest.mark.parametrize("annotation", ["str", "string"])
def test_source_password_annotation_keeps_output_schema_valid(tmp_path, annotation):
    """源码中的密码类型声明不会改坏模型输出的 JSON Schema 类型"""

    def handle(payload):
        """检查供应商实际收到的类型和引用仍是有效契约"""
        assert payload["schema"]["properties"]["reply"]["type"] == "string"
        assert payload["schema"]["type"] == "object"
        return reply()

    prompt = "分析源码\n" + json.dumps(
        {"source_materials": {"files": [{"text": f"password: {annotation}\n"}]}}
    )
    assert run(provider_at(tmp_path, handle), tmp_path, prompt).reply == "完成"


def test_schema_private_enum_restores_without_changing_protocol(tmp_path):
    """自定义栏目候选仍脱敏并还原，固定字段名和类型不被敏感词改写"""

    class Answer(Model):
        """模拟带有私人栏目名称的动态模板契约"""

        section: Literal["合成学校栏目"]

    def runner(payload, *_):
        """返回脱敏后的候选值以验证结果仍通过原始领域模型"""
        field = payload["schema"]["properties"]["section"]
        assert field["type"] == "string"
        assert "合成学校栏目" not in json.dumps(payload, ensure_ascii=False)
        return json.dumps({"section": field["const"]})

    provider = CodexProvider(runner=runner).with_private_data(
        {"personal": {"name": "string", "custom_fields": [{"value": "合成学校栏目"}]}}
    )
    result = provider.run_structured(
        result_model=Answer,
        workspace=tmp_path,
        prompt="识别模板",
        thread_id=None,
        settings=ProviderSettings(),
        cancelled=threading.Event(),
        emit=lambda *_: None,
    )
    assert result.section == "合成学校栏目"


@pytest.mark.parametrize("identity", ["source", "text"])
def test_identity_matching_material_keys_keeps_sources_readable(tmp_path, identity):
    """敏感词和材料字段同名时仍可生成沙箱副本，正文及文件名继续脱敏"""

    def handle(payload):
        """通过真实副本写入和读取验证固定路由未被敏感词破坏"""
        (tmp_path / "materials").mkdir()
        context = json.loads(
            materials(tmp_path, payload["input"], payload["schema"]).splitlines()[-1]
        )
        record = context["source_materials"]["files"][0]
        assert record["material_file"] == "source-0001.txt"
        assert TOKEN.search(record["path"])
        rows = json.loads(
            call(tmp_path / "materials", "read_material", {"file": record["material_file"]})
        )
        assert rows[0]["text"] != identity and TOKEN.search(rows[0]["text"])
        return reply(rows[0]["text"])

    provider = provider_at(tmp_path, handle).with_private_data({"personal": {"name": identity}})
    prompt = "分析源码\n" + json.dumps(
        {
            "source_materials": {
                "files": [{"source": "source-0", "path": identity + ".py", "text": identity}]
            }
        }
    )
    assert run(provider, tmp_path, prompt).reply == identity


@pytest.mark.parametrize("size", [20, 100000])
def test_source_manifest_preserves_all_linked_repositories(tmp_path, size):
    """第一个仓库超过旧文件或文字预算时，各来源仍保留按需访问入口"""
    roots = [tmp_path / "large", tmp_path / "small"]
    for root in roots:
        root.mkdir()
    for index in range(205 if size == 20 else 5):
        (roots[0] / f"file-{index:03}.py").write_text("#" * size, encoding="utf-8")
    (roots[1] / "feature.py").write_text("print('later repository')\n", encoding="utf-8")
    sources = [{"id": f"source-{i}", "path": str(root)} for i, root in enumerate(roots)]
    bundle = source_context(sources, tmp_path / "data", threading.Event())
    assert bundle["sources"] == ["source-0", "source-1"]
    assert bundle["mode"] == "on-demand"
    assert "files" not in bundle and "limited" not in bundle


@pytest.mark.parametrize("pages", [1, 13])
def test_native_pdf_recovery_does_not_require_ocr(tmp_path, monkeypatch, pages):
    """纯文字 PDF 沿用本机结构解析，不因 OCR 不可用或证书页数上限失败"""
    source = tmp_path / "native.pdf"
    with pymupdf.open() as pdf:
        for _ in range(pages):
            page = pdf.new_page(width=400, height=500)
            page.insert_text((50, 50), "Resume")
        pdf.save(source)
    original = source.read_bytes()

    def forbidden(*_):
        """原生文字模板无需加载 OCR，也不应执行模型请求"""
        pytest.fail("原生 PDF 解析不应启动 OCR 或模型")

    monkeypatch.setattr(local_ocr, "engine", forbidden)
    output = tmp_path / "restored.docx"
    package, _ = prepare_template(
        source,
        output,
        CodexProvider(runner=forbidden),
        ProviderSettings(),
        threading.Event(),
        lambda *_: None,
        simple_document(),
        [],
    )
    assert sum(row["text"] == "Resume" for row in package.inventory()["nodes"]) == pages
    assert source.read_bytes() == original
    assert "Resume" in "\n".join(p.text for p in Document(output).paragraphs)


@pytest.mark.parametrize("blank", [False, True])
def test_private_mixed_pdf_recovers_only_scanned_page(tmp_path, monkeypatch, blank):
    """混合模板只对扫描页 OCR，空结果仍保留原生页并登记不确定身份"""
    source = tmp_path / "mixed.pdf"
    pixels = BytesIO()
    Image.new("RGB", (100, 100), "white").save(pixels, format="PNG")
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=400, height=500)
        page.insert_text((50, 50), "Recipient:\nAlice Example")
        page = pdf.new_page(width=400, height=500)
        page.insert_image(page.rect, stream=pixels.getvalue())
        pdf.save(source)
    calls = []

    def recognize(*_):
        """模拟扫描页识别结果并记录实际调用次数"""
        calls.append(True)
        return {
            "width": 100,
            "height": 100,
            "blocks": []
            if blank
            else [{"text": "UncertainIdentity", "confidence": 0.4, "box": [0.1, 0.1, 0.8, 0.2]}],
        }

    monkeypatch.setattr(local_ocr, "recognize", recognize)
    provider = provider_at(tmp_path, lambda payload: reply(payload["input"]))
    package, _ = prepare_template(
        source,
        tmp_path / "restored.docx",
        provider,
        ProviderSettings(),
        threading.Event(),
        lambda *_: None,
        simple_document(),
        [],
    )
    text = "\n".join(row["text"] for row in package.inventory()["nodes"])
    assert "Alice Example" in text
    assert ("UncertainIdentity" in text) == (not blank)
    assert calls == [True]
    assert "Alice Example" in provider.sensitive_values
    if not blank:
        assert "UncertainIdentity" in provider.sensitive_values
    assert not TOKEN.search(run(provider, tmp_path, "Alice Example").reply)


def test_material_long_line_can_be_read_completely_and_searched(tmp_path):
    """长行分段可完整重组且搜索片段包含实际命中，响应始终为有界 JSON"""
    original = '\\"\t' * 9000 + "FUNCTION_AT_END"
    (tmp_path / "source-0001.txt").write_text(original + "\nlast line", encoding="utf-8")
    column, pieces = 1, []
    for _ in range(100):
        raw = call(
            tmp_path,
            "read_material",
            {"file": "source-0001.txt", "start_line": 1, "start_column": column, "line_count": 1},
        )
        assert len(raw) <= 24000
        rows = json.loads(raw)
        assert len(rows) == 1 and rows[0]["line"] == 1
        pieces.append(rows[0]["text"])
        if "next_column" not in rows[0]:
            break
        assert rows[0]["next_column"] > column
        column = rows[0]["next_column"]
    else:
        pytest.fail("长行读取未完成")
    assert "".join(pieces) == original
    matches = json.loads(call(tmp_path, "search_materials", {"query": "FUNCTION_AT_END"}))
    assert matches[0]["line"] == 1 and "FUNCTION_AT_END" in matches[0]["text"]


def test_material_many_matches_do_not_truncate_json(tmp_path):
    """多个长匹配行触及输出上限时只返回完整记录，可按行号继续读取"""
    (tmp_path / "source-0001.txt").write_text(
        "\n".join("needle" + "x" * 900 for _ in range(100)), encoding="utf-8"
    )
    for tool, arguments in (
        ("search_materials", {"query": "needle"}),
        ("read_material", {"file": "source-0001.txt", "line_count": 100}),
    ):
        raw = call(tmp_path, tool, arguments)
        assert len(raw) <= 24000
        rows = json.loads(raw)
        assert rows and all(row["text"].startswith("needle") for row in rows)
