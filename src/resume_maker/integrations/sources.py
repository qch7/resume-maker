"""项目目录定位、引用文件留存与原文证据核验"""

import hashlib
import os
import re
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryDirectory

from resume_maker.infrastructure.database import dump, now, uid
from resume_maker.integrations.providers.base import Cancelled

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
SECRET_FILE = re.compile(r"(^\.env($|\.)|credentials|^auth\.json$|private.?key|id_rsa)", re.I)
SECRET_VALUE = re.compile(
    r"(?im)([\"']?(?:api[_-]?key|access[_-]?token|secret|password|passwd|authorization)"
    r"[\"']?\s*[:=]\s*)([^\r\n,]+)"
)


def digest(data: bytes) -> str:
    """计算 SHA-256 摘要；用于输入指纹、文件完整性及导出追溯"""
    return hashlib.sha256(data).hexdigest()


def git(root: Path, *args: str) -> str:
    """在指定目录运行只读 Git 查询；非零退出码按无结果处理"""
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
    """识别符号链接和 Windows 目录联接以免扫描越出来源目录"""
    return path.is_symlink() or path.is_junction()


def source_roots(path: Path) -> list[Path]:
    """发现目录内的独立 Git 仓库；没有仓库时使用普通目录本身"""
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
    """将项目集合转换为可确认的项目分组及其源码根目录"""
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
    """遮盖明显的口令和 API 密钥；降低快照与错误日志泄露敏感值的风险"""
    text = SECRET_VALUE.sub(r"\1<redacted>", text)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{16,}\b", "<redacted>", text)


def project_sources(project: dict) -> list[dict]:
    """只解析当前关联目录及版本信息且不扫描或复制源码；让模型直接按需读取"""
    sources = []
    for index, root_name in enumerate(project["roots"]):
        root = Path(root_name).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("项目来源必须是文件夹。")
        has_git = (root / ".git").exists()
        status = git(root, "status", "--porcelain", "--untracked-files=normal") if has_git else ""
        sources.append(
            {
                "id": f"source-{index}",
                "path": str(root),
                "name": root.name,
                "commit": git(root, "rev-parse", "HEAD") if has_git else "",
                "branch": git(root, "branch", "--show-current") if has_git else "",
                "dirty": bool(status),
                "status": status,
            }
        )
    return sources


def evidence_file(sources, source, path, data_dir):
    """仅定位本轮来源内的普通文件；拒绝越界、链接、密钥文件及应用自己的资料"""
    relative = PurePosixPath(path.replace("\\", "/"))
    root_info = next((item for item in sources if item["id"] == source), None)
    if (
        root_info is None
        or relative.is_absolute()
        or PureWindowsPath(path).drive
        or ".." in relative.parts
        or ":" in path
        or SECRET_FILE.search(relative.name)
        or any(part in EXCLUDED for part in relative.parts[:-1])
    ):
        raise ValueError("引用文件必须是当前项目目录中的普通源码或文档。")
    root = Path(root_info["path"]).resolve(strict=True)
    candidate = root.joinpath(*relative.parts)
    if any(
        linked(part)
        for part in (candidate, *candidate.parents)
        if part != root and part.is_relative_to(root)
    ):
        raise ValueError("引用文件不能通过链接越出项目来源。")
    target = candidate.resolve(strict=True)
    if not target.is_relative_to(root) or target.is_relative_to(data_dir) or not target.is_file():
        raise ValueError("引用文件必须位于当前项目来源内。")
    return target, relative.as_posix()


def capture_evidence(db, data_dir, project, sources, references, cancelled=None):
    """模型完成后仅固化被引用文件；保留历史证据格式且不把整份源码复制作为分析前提"""
    data_dir = data_dir.resolve()
    snapshots = data_dir / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    files, omitted, seen = [], [], set()
    with TemporaryDirectory(prefix=".evidence-", dir=snapshots) as directory:
        staging = Path(directory)
        for item in references:
            if cancelled is not None and cancelled.is_set():
                raise Cancelled("证据核对已取消。")
            if item.get("status") not in {"code", "document"}:
                continue
            key = item["source"], item["path"]
            if key in seen:
                continue
            seen.add(key)
            try:
                path, relative = evidence_file(sources, *key, data_dir)
                before = path.stat()
                raw = path.read_bytes()
                after = path.stat()
                if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                    raise ValueError("核对时引用文件发生变化。")
                if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                    original = raw.decode("utf-16")
                else:
                    original = raw.decode("utf-8-sig")
                if "\0" in original:
                    raise ValueError("引用文件不是可读文本。")
            except (OSError, UnicodeError, ValueError) as exc:
                omitted.append({"source": key[0], "path": key[1], "reason": str(exc)})
                continue
            text = redact(original)
            stored = text.encode("utf-8")
            staged = f"{key[0]}/{relative}.source.txt"
            destination = staging / staged
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(stored)
            files.append(
                {
                    "source": key[0],
                    "path": key[1],
                    "staged": staged,
                    "sha256": digest(raw),
                    "stored_sha256": digest(stored),
                    "size": len(stored),
                    "lines": len(text.splitlines()),
                    "redacted": text != original,
                }
            )
        if cancelled is not None and cancelled.is_set():
            raise Cancelled("证据核对已取消。")
        manifest = {
            "mode": "cited-files",
            "sources": sources,
            "files": files,
            "omitted": omitted,
            "total_bytes": sum(item["size"] for item in files),
        }
        fingerprint = digest(dump(manifest).encode())
        identifier = uid()
        (staging / "manifest.json").write_text(dump(manifest), encoding="utf-8")
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO snapshots VALUES (?,?,?,?,?)",
                (identifier, project["id"], fingerprint, dump(manifest), now()),
            )
            staging.rename(snapshots / identifier)
    return db.one("SELECT * FROM snapshots WHERE id=?", (identifier,))


def check_evidence(data_dir: Path, snapshot: dict | None, evidence: list[dict]) -> list[dict]:
    """将行号和引文与留存原文比对；无记录或无法核实的引用降级为待确认"""
    entries = (
        {(f["source"], f["path"]): f for f in snapshot["manifest"]["files"]} if snapshot else {}
    )
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
        # 个人贡献和量化成果只能由用户本人确认；模型不能替用户作证
        elif item["status"] == "user":
            item["status"] = "unverified"
        result.append(item)
    return result
