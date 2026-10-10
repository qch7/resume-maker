"""导入选择、取消、损坏输出和格式隔离的公开行为"""

from dataclasses import replace
from io import BytesIO
from threading import Event

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.integrations.document_importers import importer
from resume_maker.plugin_packages.sys_documents.services.document_registry import DocumentRegistry
from resume_maker.plugins.discovery import selection
from resume_maker.runtime.host import Contribution
from resume_maker.sdk.imports import (
    DocumentImporter,
    ImportContext,
    ImportProbe,
    ImportResult,
    ImportSource,
)
from resume_maker.sdk.model import Cancelled

HEADERS = {"x-resume-token": "test"}


def registry(values):
    """建立可替换贡献集合，模拟启停及版本变化后的公开注册表"""
    return DocumentRegistry(
        lambda point: (
            tuple(
                Contribution(identifier.split("/")[0], point, identifier, value)
                for identifier, value in values.items()
            )
            if point == "documents.importers"
            else ()
        )
    )


def synthetic_importer():
    """构造只有明确文件头才匹配的两页格式"""
    image = BytesIO()
    Image.new("RGB", (10, 10), "white").save(image, format="PNG")
    return DocumentImporter(
        "1.0.0",
        "合成证书",
        ("certificate",),
        (".synthetic",),
        lambda source: ImportProbe("synthetic", 2) if source.data == b"SYNTHETIC" else None,
        lambda _source, _context: ImportResult(pages=(image.getvalue(), image.getvalue())),
    )


def test_selection_conflict_disablement_and_changed_history(tmp_path):
    """多个匹配必须明确选择，重试不能替换已消失或改变版本的处理器"""
    first = synthetic_importer()
    values = {"community.one/read": first, "community.two/read": first}
    service = registry(values)
    source = ImportSource("wrong.pdf", b"SYNTHETIC", "certificate")
    with pytest.raises(Problem, match="多个导入器"):
        service.select_importer(source)
    selected = service.select_importer(source, "community.one/read")
    result = service.run_import(selected, ImportContext(tmp_path, Event()))
    assert len(result.pages) == 2
    values["community.one/read"] = replace(first, version="2.0.0")
    with pytest.raises(Problem, match="版本已变化"):
        service.select_importer(source, expected=selected.trace)
    values.pop("community.one/read")
    with pytest.raises(Problem, match="未启用"):
        service.select_importer(source, expected=selected.trace)
    with pytest.raises(Problem, match="没有可用"):
        service.select_importer(replace(source, data=b"not synthetic"))


@pytest.mark.parametrize("failure", ["partial", "bad-png", "path", "cancelled", "bad-docx"])
def test_invalid_or_cancelled_results_never_publish(tmp_path, failure):
    """残缺页面、文件路径冒充内容和取消后的迟到输出均被拒绝"""
    base = synthetic_importer()
    context = ImportContext(tmp_path, Event())

    def prepare(source, current):
        """在真正执行返回处注入不同的坏结果"""
        result = base.prepare(source, current)
        if failure == "cancelled":
            current.cancelled.set()
        if failure == "partial":
            return replace(result, pages=result.pages[:1])
        if failure in {"bad-png", "path"}:
            return replace(result, pages=((b"damaged" if failure == "bad-png" else tmp_path),) * 2)
        if failure == "bad-docx":
            return ImportResult(template=b"not a document")
        return result

    purpose = "template" if failure == "bad-docx" else "certificate"
    value = replace(base, purposes=(purpose,), prepare=prepare)
    service = registry({"community.one/read": value})
    chosen = service.select_importer(ImportSource("example.synthetic", b"SYNTHETIC", purpose))
    with pytest.raises(Cancelled if failure == "cancelled" else Problem):
        service.run_import(chosen, context)
    assert not list(tmp_path.iterdir())


def test_actual_bytes_choose_pdf_and_multiframe_image_is_rejected(tmp_path):
    """错误扩展名不会选择错误插件，多帧图片不能静默丢页"""
    import pymupdf

    service = registry(
        {"ext.import-image/default": importer("image"), "ext.import-pdf/default": importer("pdf")}
    )
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.new_page()
        raw = pdf.tobytes()
    selected = service.select_importer(ImportSource("wrong.png", raw, "certificate"))
    assert selected.trace["id"] == "ext.import-pdf/default"
    assert len(service.run_import(selected, ImportContext(tmp_path, Event())).pages) == 2
    animated = BytesIO()
    frames = [Image.new("RGB", (10, 10), color) for color in ("white", "black")]
    frames[0].save(animated, format="TIFF", save_all=True, append_images=frames[1:])
    with pytest.raises(Problem, match="多页或动态图片"):
        service.select_importer(ImportSource("scan.tiff", animated.getvalue(), "certificate"))


def test_minimal_does_not_offer_optional_importers_and_retains_manual_honors(tmp_path):
    """最小组合新增荣誉库后仍可手工使用，不借安装环境偷用图片或 PDF 库"""
    selected = selection("minimal")[1] | {"ext.honors"}
    app = create_app(Config(data_dir=tmp_path / "data", plugins=tuple(selected), token="test"))
    with TestClient(app) as client:
        assert (
            client.get("/api/document-importers?purpose=certificate", headers=HEADERS).json() == []
        )
        entries = client.get("/api/document-importers?purpose=template", headers=HEADERS).json()
        assert [row["id"] for row in entries] == ["sys.docx/import"]
        assert (
            client.get("/api/document-importers?purpose=unknown", headers=HEADERS).status_code
            == 422
        )
        assert client.get("/api/document-importers").status_code == 401
        response = client.post(
            "/api/honors/upload?filename=test.png", content=b"PNG", headers=HEADERS
        )
        assert response.status_code == 415
        assert client.get("/api/honors", headers=HEADERS).json() == []
        assert not list((tmp_path / "data" / "honors").iterdir())
        assert (
            client.post(
                "/api/honors", json={"fields": {"name": "合成荣誉"}}, headers=HEADERS
            ).status_code
            == 200
        )
