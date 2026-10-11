"""备份历史只读取本机普通 ZIP，旧备份不推断来源"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from resume_maker.core.errors import Problem


def backup_path(directory: Path, identifier: str) -> Path:
    """仅接受备份目录内的普通文件，拒绝越界及链接"""
    folder = directory / "backups"
    if (
        not identifier.endswith(".zip")
        or identifier.startswith(".")
        or len(identifier) > 255
        or any(character in identifier for character in "/\\:\x00")
        or Path(identifier).name != identifier
        or folder.is_symlink()
        or folder.is_junction()
    ):
        raise Problem("备份文件位置无效。", 400)
    path = folder / identifier
    if (
        path.is_symlink()
        or path.is_junction()
        or not path.resolve().is_relative_to(folder.resolve())
    ):
        raise Problem("备份文件位置无效。", 400)
    if not path.is_file():
        raise Problem("备份不存在或已被删除。", 404)
    return path


def backup_digest(path: Path) -> str:
    """恢复计划固定文件摘要，应用时拒绝被替换的备份"""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def backup_record(path: Path) -> dict:
    """列表读取有界清单，损坏备份仍可辨认及删除"""
    stamp = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    record = {
        "id": path.name,
        "created_at": stamp,
        "size": path.stat().st_size,
        "kind": "unknown",
        "reason": None,
        "restorable": False,
        "error": None,
    }
    try:
        with ZipFile(path) as archive:
            info = archive.getinfo("backup.json")
            if info.file_size > 4_000_000:
                raise ValueError("备份清单过大。")
            metadata = json.loads(archive.read(info))
        if not isinstance(metadata, dict) or metadata.get("version") != 2:
            raise ValueError("备份格式版本不受支持。")
        if not isinstance(metadata.get("files"), dict) or "resume.db" not in metadata["files"]:
            raise ValueError("备份文件清单不完整。")
        created = datetime.fromisoformat(metadata["created_at"])
        if created.tzinfo is None:
            raise ValueError("备份时间缺少时区。")
        record["created_at"] = created.astimezone(UTC).isoformat()
        record["kind"] = (
            metadata.get("kind") if metadata.get("kind") in {"manual", "automatic"} else "unknown"
        )
        reason = metadata.get("reason")
        record["reason"] = reason if isinstance(reason, str) and len(reason) <= 100 else None
        record["restorable"] = True
    except (BadZipFile, OSError, KeyError, ValueError, TypeError, RuntimeError):
        record["error"] = "备份清单损坏或格式不受支持，无法恢复。"
    return record


def list_backups(directory: Path) -> list[dict]:
    """只列已发布 ZIP，临时压缩文件及迁移数据库不进入历史"""
    folder = directory / "backups"
    if folder.is_symlink() or folder.is_junction():
        raise Problem("备份目录不能包含链接。", 400)
    records = []
    for candidate in folder.glob("*.zip"):
        try:
            records.append(backup_record(backup_path(directory, candidate.name)))
        except Problem:
            continue
        except FileNotFoundError:
            continue
    return sorted(records, key=lambda item: (item["created_at"], item["id"]), reverse=True)


def protected_backups(manager) -> set[str]:
    """正在恢复或升级的恢复点保持可用，结束后允许用户删除"""
    protected = set()
    for plan in manager.plans.values():
        if plan.get("restore_backup") and plan["state"] in {
            "planned",
            "preparing",
            "restart-required",
        }:
            protected.add(plan["restore_backup"]["id"])
    directory = manager.host.bootstrap["config"].data_dir
    for name in ("host-transition.json", "host-restore.json"):
        path = directory / name
        if path.is_file():
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("state") in {"prepared", "applying", "booting", "recovery-required"}:
                if value.get("backup"):
                    protected.add(Path(value["backup"]).name)
                if value.get("archive"):
                    protected.add(value["archive"])
    return protected
