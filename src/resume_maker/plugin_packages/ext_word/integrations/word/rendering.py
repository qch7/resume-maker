"""隔离 Word 渲染和预览图片生成并只回收本次启动的 Word 实例"""

import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import psutil

from resume_maker.core.process_environment import EnvironmentPolicy, process_environment
from resume_maker.infrastructure.observability import operation, record
from resume_maker.plugin_packages.ext_word.configuration import Settings
from resume_maker.sdk.documents import check_document_work, current_document_work
from resume_maker.sdk.model import ProviderError

# Word COM 排版串行运行以免并发导出争用桌面实例
RENDER_LOCK = threading.Lock()


@contextmanager
def render_lock():
    """等候 Word 时仍检查当前预览的取消和总截止"""
    while not RENDER_LOCK.acquire(timeout=0.05):
        check_document_work()
    try:
        check_document_work()
        yield
    finally:
        RENDER_LOCK.release()


def render_pages(pdf: Path, *, settings=None) -> int:
    """从同一 Word PDF 生成分页图，文字转矢量轮廓以免放大模糊或缺少字体"""
    import pymupdf

    settings = settings or Settings()
    with pymupdf.open(pdf) as document:
        for index, page in enumerate(document):
            check_document_work(pdf.parent)
            (pdf.parent / f"page-{index + 1}.svg").write_text(
                page.get_svg_image(text_as_path=True), encoding="utf-8"
            )
            page.get_pixmap(
                matrix=pymupdf.Matrix(settings.preview_scale, settings.preview_scale)
            ).save(pdf.parent / f"page-{index + 1}.png")
            check_document_work(pdf.parent)
        return len(document)


@operation("word.process", "system")
def word_process(
    source: Path, output: Path, mode="render", *, executor=None, settings=None
) -> str | None:
    """隔离执行 Word 的转换或排版且只回收本次启动的进程，失败返回具体原因"""
    settings = settings or Settings()
    if os.name != "nt":
        record("system", "unavailable", "Word 自动转换不可用", level="warning", source="word")
        return "此自动转换需要 Windows 上的 Microsoft Word。"
    with render_lock():
        timeout = settings.render_timeout_seconds
        if work := current_document_work():
            timeout = min(timeout, max(0.01, work.deadline - time.monotonic()))
        owner_file = output.with_suffix(".owner.json")
        try:
            if executor is not None:
                executor(
                    [
                        sys.executable,
                        "-X",
                        "utf8",
                        "-m",
                        "resume_maker.plugin_packages.ext_word.integrations.word.worker",
                        str(source),
                        str(output),
                        str(owner_file),
                        mode,
                    ],
                    cwd=source.parent,
                    timeout=timeout,
                )
                return None if output.exists() else "Word 没有生成输出文件。"
            result = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-m",
                    "resume_maker.plugin_packages.ext_word.integrations.word.worker",
                    str(source),
                    str(output),
                    str(owner_file),
                    mode,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=0x08000000,
                env=process_environment(EnvironmentPolicy.DESKTOP),
            )
            if result.returncode or not output.exists():
                record(
                    "system",
                    "failed",
                    "Word 自动处理失败",
                    {"exit_code": result.returncode, "stderr": result.stderr},
                    source="word",
                    level="error",
                )
                detail = result.stderr.strip().splitlines()
                return "Word 自动处理失败。" + (detail[-1][:300] if detail else "")
            return None
        except (OSError, subprocess.TimeoutExpired, ProviderError) as exc:
            record(
                "system",
                "failed",
                "Word 进程异常或超时",
                {"error": str(exc)},
                source="word",
                level="error",
            )
            return f"Word 自动处理失败：{exc}"
        finally:
            if owner_file.exists():
                try:
                    owner = json.loads(owner_file.read_text())
                    process = psutil.Process(owner["pid"])
                    if (
                        process.create_time() == owner["created"]
                        and process.name().lower() == "winword.exe"
                    ):
                        process.kill()
                except (psutil.Error, OSError, ValueError):
                    pass
                owner_file.unlink(missing_ok=True)


def render_word(
    docx: Path, pdf: Path, *, executor=None, settings=None
) -> tuple[int | None, str | None]:
    """串行生成 PDF 和分页图片，失败仍保留已生成的 DOCX"""
    options = {"settings": settings} if settings is not None else {}
    if executor is not None:
        options["executor"] = executor
    error = word_process(docx, pdf, **options)
    if error:
        return None, error
    pages = render_pages(pdf) if settings is None else render_pages(pdf, settings=settings)
    return pages, None


def convert_word(source: Path, output: Path) -> str | None:
    """将旧版或可修复的 Word 文档另存为 DOCX 副本"""
    return word_process(source, output, "convert")
