"""统一选择和校验导入器，冲突、版本变化和残缺输出都不能静默发布"""

from dataclasses import dataclass, replace
from io import BytesIO

from docx.image.image import Image

from resume_maker.core.errors import Problem
from resume_maker.integrations.document_limits import (
    CERTIFICATE_MAX_PAGES,
    SAFE_PAGE_MAX_BYTES,
    SOURCE_IMAGE_MAX_PIXELS,
    TEMPLATE_MAX_BYTES,
    import_limits,
)
from resume_maker.integrations.word.templates.mapping import TemplatePackage
from resume_maker.sdk.imports import DocumentImporter, ImportProbe, ImportResult, ImportSource
from resume_maker.sdk.model import Cancelled


@dataclass(frozen=True)
class SelectedImport:
    """固定当前贡献和原件，持久记录可在重试时精确核对"""

    source: ImportSource
    importer: DocumentImporter
    trace: dict
    renderer: object = None


class ImporterRegistry:
    """复用宿主贡献集合，不按安装或加载顺序挑选处理器"""

    def importers(self, purpose):
        """向界面公开当前可用格式，声明的扩展名不替代实际内容探测"""
        if purpose not in {"template", "certificate"}:
            raise Problem("导入用途无效。", 422)
        return [
            {
                "id": item.identifier,
                "owner": item.owner,
                "version": item.value.version,
                "title": item.value.title,
                "extensions": list(item.value.extensions),
                "limits": import_limits(purpose),
            }
            for item in self.entries("documents.importers", DocumentImporter).values()
            if purpose in item.value.purposes
        ]

    def select_importer(self, source, identifier=None, *, expected=None):
        """唯一匹配时自动选择，多项匹配或历史绑定失效时保留输入并要求明确处理"""
        if source.purpose not in {"template", "certificate"}:
            raise Problem("导入用途无效。", 422)
        limit = import_limits(source.purpose)["max_bytes"]
        if not source.data or len(source.data) > limit:
            raise Problem(f"文件不能为空且不得超过 {limit // 1_000_000} MB。", 413)
        entries = self.entries("documents.importers", DocumentImporter)
        if expected is not None:
            identifier = expected["id"]
        if identifier and identifier not in entries:
            raise Problem(f"导入器未启用：{identifier}。原件仍保留，请启用后重试。", 409)
        matches, errors = [], []
        for item in entries.values():
            if identifier and item.identifier != identifier:
                continue
            importer = item.value
            if source.purpose not in importer.purposes:
                continue
            try:
                probe = importer.probe(source)
            except Exception as exc:
                if identifier:
                    raise Problem(f"{importer.title} 无法读取此文件：{exc}", 415) from exc
                errors.append(f"{importer.title}：{exc}")
                continue
            if probe is None:
                continue
            if (
                not isinstance(probe, ImportProbe)
                or not isinstance(probe.format, str)
                or not probe.format
                or len(probe.format) > 80
                or (probe.pages is not None and (type(probe.pages) is not int or probe.pages < 1))
                or (source.purpose == "certificate" and not probe.pages)
            ):
                raise Problem(f"导入器探测结果无效：{item.identifier}", 409)
            if source.purpose == "certificate" and probe.pages > CERTIFICATE_MAX_PAGES:
                raise Problem(f"每份证书支持 1–{CERTIFICATE_MAX_PAGES} 页，请将不同证书分别上传。")
            trace = {
                "id": item.identifier,
                "owner": item.owner,
                "version": importer.version,
                "source_sha256": source.sha256,
                "format": probe.format,
                "pages": probe.pages,
                **self.provenance(item.owner),
            }
            renderer = self.renderer() if importer.uses_renderer else None
            if importer.uses_renderer:
                trace["renderer"] = (
                    {
                        "id": renderer.identifier,
                        "version": renderer.value.version,
                        **self.provenance(renderer.owner),
                    }
                    if renderer
                    else None
                )
            if expected is not None and trace != expected:
                raise Problem("原件或导入器版本已变化。请保留原任务，重新导入并选择处理器。", 409)
            matches.append(
                SelectedImport(source, importer, trace, renderer.value.render if renderer else None)
            )
        if not matches:
            reason = "；".join(errors) if errors else "请启用支持此内容的导入插件或选择其他处理器。"
            raise Problem("没有可用的文件导入器。" + reason, 415)
        if len(matches) > 1:
            raise Problem(
                "多个导入器可以处理此文件，请明确选择："
                + "、".join(f"{row.importer.title}（{row.trace['id']}）" for row in matches),
                409,
            )
        return matches[0]

    def run_import(self, selected, context):
        """执行后完整验证结果并复核取消，只有不可变字节能返回到业务发布入口"""
        if context.cancelled.is_set():
            raise Cancelled("文件导入已取消。")
        result = selected.importer.prepare(
            selected.source, replace(context, renderer=selected.renderer)
        )
        if context.cancelled.is_set():
            raise Cancelled("文件导入已取消，结果未发布。")
        if (
            not isinstance(result, ImportResult)
            or not isinstance(result.text, str)
            or len(result.text) > 100_000
            or not isinstance(result.notices, tuple)
            or any(not isinstance(note, str) or len(note) > 4000 for note in result.notices)
            or len(result.notices) > 200
        ):
            raise Problem("导入器返回了无效结果，未保存任何资料。", 409)
        if selected.source.purpose == "template":
            if type(result.template) is not bytes or not result.template or result.pages:
                raise Problem("模板导入器必须返回完整 DOCX。", 409)
            if len(result.template) > TEMPLATE_MAX_BYTES:
                raise Problem("导入后的模板超过 100 MB。", 413)
            TemplatePackage(BytesIO(result.template))
        else:
            if (
                result.template is not None
                or not isinstance(result.pages, tuple)
                or len(result.pages) != selected.trace["pages"]
            ):
                raise Problem("证书导入页数与原件不符，未保存残缺结果。", 409)
            for page in result.pages:
                validate_page(page)
        if context.cancelled.is_set():
            raise Cancelled("文件导入已取消，结果未发布。")
        return result


def validate_page(page):
    """限制 PNG 页面大小并用基础安装已有的图片解析器检查结构和像素"""
    if (
        type(page) is not bytes
        or len(page) > SAFE_PAGE_MAX_BYTES
        or not page.startswith(b"\x89PNG\r\n\x1a\n")
    ):
        raise Problem("证书导入器未返回有效 PNG 页面。", 409)
    try:
        image = Image.from_blob(page)
        if not 0 < image.px_width * image.px_height <= SOURCE_IMAGE_MAX_PIXELS:
            raise ValueError("页面像素超出范围")
    except Exception as exc:
        raise Problem("证书页面损坏或像素超限，未保存任何资料。", 409) from exc
