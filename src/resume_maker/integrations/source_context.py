"""本机收集有界源码文本，模型仅接收文字包且不能直接读取文件"""

import os
from pathlib import Path

from resume_maker.integrations.providers.base import Cancelled
from resume_maker.integrations.sources import EXCLUDED, SECRET_FILE, evidence_file, linked

SKIP = EXCLUDED | {"data", "exports", "backups", "snapshots", "workspaces", "certificates"}
BINARY = {
    ".pdf",
    ".docx",
    ".doc",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
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
    ".lock",
}


def source_context(sources, data_dir, cancelled):
    """保留相对路径和原始行号，跳过链接、凭据、应用资料及超限内容"""
    files, omitted = [], 0
    remaining, visited, directories = 350_000, 0, 0
    for source in sources:
        root = Path(source["path"])
        for directory, dirs, names in os.walk(root, followlinks=False):
            directories += 1
            if cancelled.is_set():
                raise Cancelled("源码收集已取消。")
            if directories > 10000:
                return {
                    "files": files,
                    "limited": True,
                    "omitted": omitted,
                    "notice": "目录数量达到预算，请缩小关联目录后重新分析。",
                }
            parent = Path(directory)
            dirs[:] = sorted(
                name
                for name in dirs
                if name.lower() not in SKIP
                and not SECRET_FILE.search(name)
                and not linked(parent / name)
                and not (parent / name).resolve().is_relative_to(data_dir.resolve())
            )
            names.sort(key=lambda name: (not name.lower().startswith("readme"), name))
            for name in names:
                if cancelled.is_set():
                    raise Cancelled("源码收集已取消。")
                visited += 1
                if visited > 10000 or remaining <= 0 or len(files) >= 200:
                    return {
                        "files": files,
                        "limited": True,
                        "omitted": omitted,
                        "notice": "材料达到预算，仅分析已提供文件；未提供的实现必须标为无法核实。",
                    }
                path = parent / name
                if SECRET_FILE.search(name) or path.suffix.lower() in BINARY:
                    omitted += 1
                    continue
                relative = path.relative_to(root).as_posix()
                try:
                    safe_path, _ = evidence_file(sources, source["id"], relative, data_dir)
                    # 有界读取避免文件在 stat 后增长导致一次读入超大文件
                    with safe_path.open("rb") as stream:
                        raw = stream.read(128_001)
                    if len(raw) > 128_000 or b"\0" in raw:
                        omitted += 1
                        continue
                    text = raw.decode("utf-8-sig")
                except (OSError, UnicodeError, ValueError):
                    omitted += 1
                    continue
                if len(text) > remaining:
                    omitted += 1
                    continue
                files.append(
                    {"source": source["id"], "path": relative, "line_start": 1, "text": text}
                )
                remaining -= len(text)
    return {
        "files": files,
        "limited": False,
        "omitted": omitted,
        "notice": "仅分析提供的文字材料，未提供或跳过的文件不能作为证据。",
    }
