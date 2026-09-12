"""隔离 Word 渲染与预览图片生成，并只回收本次启动的 Word 实例。"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import psutil
import pymupdf

# Word COM 排版串行运行，避免并发导出争用桌面实例。
RENDER_LOCK = threading.Lock()


def render_word(docx: Path, pdf: Path) -> tuple[int | None, str | None]:
    """串行调用隔离的 Word 进程生成 PDF 和分页图片，失败仍保留 DOCX。"""
    if os.name != "nt":
        return None, "本版本的精确预览需要 Windows 上的 Microsoft Word；DOCX 已生成。"
    with RENDER_LOCK:
        owner_file = pdf.with_suffix(".owner.json")
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "resume_maker.integrations.word.worker",
                    str(docx),
                    str(pdf),
                    str(owner_file),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                creationflags=0x08000000,
            )
            if result.returncode or not pdf.exists():
                detail = result.stderr.strip().splitlines()
                return None, "Word 渲染失败，DOCX 仍可下载。" + (detail[-1][:300] if detail else "")
            with pymupdf.open(pdf) as document:
                for index, page in enumerate(document):
                    page.get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3)).save(
                        pdf.parent / f"page-{index + 1}.png"
                    )
                return len(document), None
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"Word 预览失败：{exc}"
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
