"""隔离 Word 渲染与预览图片生成并只回收本次启动的 Word 实例"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import psutil
import pymupdf

# Word COM 排版串行运行以免并发导出争用桌面实例
RENDER_LOCK = threading.Lock()


def render_pages(pdf: Path) -> int:
    """从同一 Word PDF 生成分页图；文字转矢量轮廓以免放大模糊或缺少字体"""
    with pymupdf.open(pdf) as document:
        for index, page in enumerate(document):
            (pdf.parent / f"page-{index + 1}.svg").write_text(
                page.get_svg_image(text_as_path=True), encoding="utf-8"
            )
            page.get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3)).save(
                pdf.parent / f"page-{index + 1}.png"
            )
        return len(document)


def word_process(source: Path, output: Path, mode="render") -> str | None:
    """隔离执行 Word 的转换或排版且只回收本次启动的进程；失败返回具体原因"""
    if os.name != "nt":
        return "此自动转换需要 Windows 上的 Microsoft Word。"
    with RENDER_LOCK:
        owner_file = output.with_suffix(".owner.json")
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "resume_maker.integrations.word.worker",
                    str(source),
                    str(output),
                    str(owner_file),
                    mode,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                creationflags=0x08000000,
            )
            if result.returncode or not output.exists():
                detail = result.stderr.strip().splitlines()
                return "Word 自动处理失败。" + (detail[-1][:300] if detail else "")
            return None
        except (OSError, subprocess.TimeoutExpired) as exc:
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


def render_word(docx: Path, pdf: Path) -> tuple[int | None, str | None]:
    """串行生成 PDF 和分页图片；失败仍保留已生成的 DOCX"""
    error = word_process(docx, pdf)
    return (None, error) if error else (render_pages(pdf), None)


def convert_word(source: Path, output: Path) -> str | None:
    """将旧版 Word 或可修复文档保存为独立 DOCX 副本且不修改源文件"""
    return word_process(source, output, "convert")
