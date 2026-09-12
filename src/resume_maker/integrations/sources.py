"""项目来源扫描、受控文本快照与原文证据核验。"""

import hashlib
import os
import re
import subprocess
from pathlib import Path

from resume_maker.infrastructure.database import Database, dump, now, uid

EXCLUDED = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    "target",
    ".idea",
    ".vscode",
    ".next",
    "coverage",
    ".cache",
    ".codex",
    ".claude",
    "logs",
    "vendor",
    "bin",
    "obj",
    ".local",
}
TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".rst",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".rb",
    ".php",
    ".sql",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".css",
    ".scss",
    ".sh",
    ".ps1",
    ".bat",
    ".ini",
    ".cfg",
    ".proto",
    ".gradle",
}
SECRET_FILE = re.compile(r"(^\.env($|\.)|credentials|^auth\.json$|private.?key|id_rsa)", re.I)
SECRET_VALUE = re.compile(
    r"(?im)([\"']?(?:api[_-]?key|access[_-]?token|secret|password|passwd|authorization)"
    r"[\"']?\s*[:=]\s*)([^\r\n,]+)"
)


def digest(data: bytes) -> str:
    """计算 SHA-256 摘要，用于输入指纹、文件完整性及导出追溯。"""
    return hashlib.sha256(data).hexdigest()


def git(root: Path, *args: str) -> str:
    """在指定目录运行只读 Git 查询，非零退出码按无结果处理。"""
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        timeout=20,
        encoding="utf-8",
        errors="replace",
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def linked(path: Path) -> bool:
    """识别符号链接和 Windows 目录联接，避免扫描越出来源目录。"""
    return path.is_symlink() or path.is_junction()


def source_roots(path: Path) -> list[Path]:
    """发现目录内的独立 Git 仓库；没有仓库时使用普通目录本身。"""
    if (path / ".git").exists():
        return [path]
    repos = []
    for directory, dirs, _ in os.walk(path, followlinks=False):
        root = Path(directory)
        dirs[:] = [n for n in dirs if n not in EXCLUDED and not linked(root / n)]
        if root != path and (root / ".git").exists():
            repos.append(root)
            dirs.clear()
    return sorted(repos) or [path]


def scan_collection(path: Path) -> list[dict]:
    """将项目集合转换为可确认的项目分组及其源码根目录。"""
    path = path.expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("项目集合必须是文件夹。")
    candidates = (
        [path]
        if (path / ".git").exists()
        else [
            p
            for p in sorted(path.iterdir())
            if p.is_dir() and not linked(p) and p.name not in EXCLUDED
        ]
    )
    return [{"name": p.name, "roots": [str(r) for r in source_roots(p)]} for p in candidates]


def redact(text: str) -> str:
    """遮盖明显的口令和 API 密钥，降低快照与错误日志泄露敏感值的风险。"""
    text = SECRET_VALUE.sub(r"\1<redacted>", text)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{16,}\b", "<redacted>", text)


def collect_snapshot(db: Database, data_dir: Path, project: dict) -> dict:
    """采集受大小限制的文本副本，记录 Git 状态、哈希、来源及遗漏原因。"""
    snapshot_id = uid()
    target = data_dir / "snapshots" / snapshot_id
    target.mkdir(parents=True)
    files, sources, omitted = [], [], []
    total = 0
    for index, root_name in enumerate(project["roots"]):
        root = Path(root_name).resolve(strict=True)
        source_id = f"source-{index}"
        has_git = (root / ".git").exists()
        commit = git(root, "rev-parse", "HEAD") if has_git else ""
        status = git(root, "status", "--porcelain", "--untracked-files=normal") if has_git else ""
        sources.append(
            {
                "id": source_id,
                "path": str(root),
                "name": root.name,
                "commit": commit,
                "branch": git(root, "branch", "--show-current") if has_git else "",
                "dirty": bool(status),
                "status": status,
            }
        )
        for directory, dirs, names in os.walk(root, followlinks=False):
            base = Path(directory)
            dirs[:] = sorted(n for n in dirs if n not in EXCLUDED and not linked(base / n))
            for name in sorted(names):
                path = base / name
                relative = path.relative_to(root).as_posix()
                if (
                    linked(path)
                    or SECRET_FILE.search(name)
                    or name.endswith((".lock", "-lock.json"))
                ):
                    continue
                if path.suffix.lower() not in TEXT_SUFFIXES and name not in {
                    "Dockerfile",
                    "Makefile",
                }:
                    continue
                if len(files) >= 3000 or total >= 25_000_000:
                    omitted.append({"source": source_id, "path": relative, "reason": "总量限制"})
                    continue
                try:
                    before = path.stat()
                    if before.st_size > 512_000:
                        omitted.append(
                            {"source": source_id, "path": relative, "reason": "文件过大"}
                        )
                        continue
                    raw = path.read_bytes()
                    after = path.stat()
                    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                        raise ValueError(f"采集时文件发生变化，请重试：{relative}")
                    if b"\0" in raw:
                        continue
                    original = raw.decode("utf-8-sig")
                except (OSError, UnicodeError) as exc:
                    omitted.append(
                        {"source": source_id, "path": relative, "reason": type(exc).__name__}
                    )
                    continue
                text = redact(original)
                stored = text.encode("utf-8")
                # 追加文本后缀，让来源中的指令文件保持为分析数据，不成为工作区指令。
                staged = f"{source_id}/{relative}.source.txt"
                destination = target / staged
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(stored)
                total += len(stored)
                files.append(
                    {
                        "source": source_id,
                        "path": relative,
                        "staged": staged,
                        "sha256": digest(raw),
                        "stored_sha256": digest(stored),
                        "size": len(stored),
                        "lines": len(text.splitlines()),
                        "redacted": text != original,
                    }
                )
        if has_git and (
            git(root, "rev-parse", "HEAD") != commit
            or git(root, "status", "--porcelain", "--untracked-files=normal") != status
        ):
            raise ValueError("采集时 Git 工作区发生变化，请等待修改完成后重试。")
    if not files:
        raise ValueError("未找到可分析的文本文件，请检查项目路径和过滤范围。")
    fingerprint = digest(dump({"sources": sources, "files": files}).encode())
    manifest = {"sources": sources, "files": files, "omitted": omitted, "total_bytes": total}
    (target / "manifest.json").write_text(dump(manifest), encoding="utf-8")
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO snapshots VALUES (?,?,?,?,?)",
            (snapshot_id, project["id"], fingerprint, dump(manifest), now()),
        )
    return db.one("SELECT * FROM snapshots WHERE id=?", (snapshot_id,))


def check_evidence(data_dir: Path, snapshot: dict, evidence: list[dict]) -> list[dict]:
    """将证据行号和引文与固定快照比对，无法核实的引用降级为待确认。"""
    entries = {(f["source"], f["path"]): f for f in snapshot["manifest"]["files"]}
    result = []
    for item in evidence:
        item = dict(item)
        source = entries.get((item["source"], item["path"]))
        if item["status"] in {"code", "document"}:
            valid = False
            if source and 0 < item["line_start"] <= item["line_end"] <= source["lines"]:
                text = (data_dir / "snapshots" / snapshot["id"] / source["staged"]).read_text(
                    encoding="utf-8"
                )
                excerpt = "\n".join(text.splitlines()[item["line_start"] - 1 : item["line_end"]])
                valid = bool(item["quote"].strip()) and item["quote"].strip() in excerpt
            if not valid:
                item["status"] = "unverified"
        # 个人贡献和量化成果只能由用户本人确认，模型不能替用户作证。
        elif item["status"] == "user":
            item["status"] = "unverified"
        result.append(item)
    return result
