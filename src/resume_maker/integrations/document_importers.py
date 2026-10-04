"""内置格式适配器使用公开导入契约，具体解码库只在对应插件使用时加载"""

import json
from io import BytesIO

from resume_maker.core.errors import Problem
from resume_maker.domain.resume import ResumeDocument
from resume_maker.integrations.word.templates.mapping import TemplatePackage
from resume_maker.sdk.imports import DocumentImporter, ImportProbe, ImportResult

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")


def docx_probe(source, *, scanned=False):
    """只认实际 DOCX 内容，可编辑模板和纯图片模板交由不同处理器"""
    if source.purpose != "template" or not source.data.startswith(b"PK"):
        return None
    package = TemplatePackage(BytesIO(source.data))
    nodes = package.inventory()["nodes"]
    is_scanned = any(row["kind"] == "image" for row in nodes) and not any(
        row["kind"] == "p" and row["text"].strip() for row in nodes
    )
    return ImportProbe("docx") if is_scanned == scanned else None


def pdf_probe(source):
    """核验 PDF 实际格式、密码和源页数，扩展名不参与判断"""
    if not source.data.lstrip().startswith(b"%PDF-"):
        return None
    import pymupdf

    with pymupdf.open(stream=source.data, filetype="pdf") as document:
        if document.needs_pass:
            raise Problem("PDF 已加密，请先移除密码再导入。")
        if not len(document):
            raise Problem("PDF 没有页面。")
        return ImportProbe("pdf", len(document))


def image_probe(source):
    """核验图片真实格式和帧数，拒绝只导入多帧文件的第一页"""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(BytesIO(source.data)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP", "BMP", "TIFF"}:
                return None
            if getattr(image, "n_frames", 1) != 1:
                raise Problem("请将多页或动态图片转为 PDF，或拆分为单张图片。")
            if image.width * image.height > 40_000_000:
                raise Problem("图片超过 4000 万像素，请缩小后上传。")
            format_name = image.format.lower()
            image.verify()
            return ImportProbe(format_name, 1)
    except UnidentifiedImageError:
        return None


def word_probe(source):
    """旧 Word 只接受真实复合文档头，损坏 DOCX 由明确的修复选择处理"""
    if source.purpose != "template":
        return None
    if source.data.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        return ImportProbe("doc")
    if source.data.startswith(b"PK"):
        try:
            TemplatePackage(BytesIO(source.data))
        except Problem:
            return ImportProbe("damaged-docx")
    return None


def prepare_certificate(source, context, kind):
    """复用本地证书解码器，原件命名和业务发布由调用方统一负责"""
    from resume_maker.integrations.certificates import prepare_certificate as prepare

    metadata = prepare(
        source.data, "source.pdf" if kind == "pdf" else "source.png", context.workspace
    )
    return ImportResult(
        pages=tuple(
            (context.workspace / f"page-{number}.png").read_bytes()
            for number in range(1, metadata["pages"] + 1)
        ),
        text=metadata["text"],
    )


def prepare_template(source, context, kind, converter=None):
    """已选格式直接进入恢复分支，模型请求仍使用注入的独立隐私上下文"""
    from resume_maker.integrations.word.recovery import prepare_template as prepare

    original = context.workspace / ("source.doc" if kind == "word" else "source." + kind)
    output = context.workspace / "prepared.docx"
    original.write_bytes(source.data)
    _, notices = prepare(
        original,
        output,
        context.provider,
        context.settings,
        context.cancelled,
        context.emit or (lambda _kind, _data: None),
        ResumeDocument.model_validate_json(context.document_json),
        json.loads(context.projects_json),
        renderer=context.renderer,
        converter=converter,
        importers={"pdf": True} if kind in {"pdf", "scanned-docx"} else {},
        source_format="docx" if kind == "scanned-docx" else kind,
    )
    return ImportResult(template=output.read_bytes(), notices=tuple(notices))


def importer(kind, *, converter=None):
    """为各内置插件构造同一公开协议的格式贡献"""

    def probe(source):
        """按适配器声明探测实际内容，图片 DOCX 不和普通 DOCX 抢占同一输入"""
        if kind == "scanned-docx":
            return docx_probe(source, scanned=True)
        return {"docx": docx_probe, "pdf": pdf_probe, "image": image_probe, "word": word_probe}[
            kind
        ](source)

    def prepare(source, context):
        """模板恢复和证书分页共用同一个显式格式选择"""
        if source.purpose == "certificate":
            return prepare_certificate(source, context, kind)
        return prepare_template(source, context, kind, converter)

    titles = {
        "docx": "可编辑 Word 模板",
        "scanned-docx": "图片型 Word 模板恢复",
        "pdf": "PDF 导入",
        "image": "图片导入",
        "word": "旧版或损坏的 Word 转换",
    }
    extensions = {
        "docx": (".docx",),
        "scanned-docx": (".docx",),
        "pdf": (".pdf",),
        "image": IMAGE_EXTENSIONS,
        "word": (".doc", ".docx"),
    }
    return DocumentImporter(
        "1.0.0",
        titles[kind],
        ("template", "certificate") if kind in {"image", "pdf"} else ("template",),
        extensions[kind],
        probe,
        prepare,
        uses_renderer=kind == "scanned-docx",
    )
