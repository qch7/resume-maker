"""声明本轮来源并按需遍历，项目总量不决定可读范围"""

import os
from pathlib import Path

from resume_maker.core.config import sandbox_directory
from resume_maker.integrations.providers.base import Cancelled
from resume_maker.integrations.sources import EXCLUDED, SECRET_FILE, linked

BINARY = {
    ".pdf",
    ".docx",
    ".doc",
    ".png",
    ".jpg",
    ".jpeg",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".zip",
    ".pem",
    ".key",
    ".pfx",
    ".p12",
    ".exe",
    ".dll",
}


def source_paths(root, data_dir, cancelled):
    """逐个产出候选文件，跳过链接、凭据、应用数据和运行沙箱"""
    private_roots = (data_dir, sandbox_directory().resolve())
    for directory, dirs, names in os.walk(root, followlinks=False):
        if cancelled.is_set():
            raise Cancelled("源码读取已取消。")
        yield None
        parent = Path(directory)
        if any(parent.resolve().is_relative_to(private) for private in private_roots):
            dirs.clear()
            continue
        dirs[:] = sorted(
            name
            for name in dirs
            if name.lower() not in EXCLUDED
            and not SECRET_FILE.search(name)
            and not linked(parent / name)
            and not any(
                (parent / name).resolve().is_relative_to(private) for private in private_roots
            )
        )
        names.sort(key=lambda name: (not name.lower().startswith("readme"), name))
        for name in names:
            yield parent / name


def source_context(sources, data_dir, cancelled):
    """只声明工具入口，启动模型前不枚举文件或读取整库正文"""
    if cancelled.is_set():
        raise Cancelled("源码读取已取消。")
    return {
        "mode": "on-demand",
        "sources": [item["id"] for item in sources],
        "notice": "使用 list_source_files、search_sources 和 read_source 按需访问所有关联来源。"
        "每次结果有界，存在 next_cursor 或 next 时继续读取，不能把单页结果当成全部材料。"
        "原件留在本机，返回内容已脱敏；引用使用返回的 source、path 和原始行号。",
    }
