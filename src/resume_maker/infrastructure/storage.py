"""离线恢复和应用服务器共用实例锁以免数据目录被并发覆盖"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path, PurePosixPath
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import SCHEMA_VERSION, Database, dump, now, uid

FOLDERS = ("templates", "snapshots", "exports", "honors", "template-drafts")


@contextmanager
def instance_lock(directory: Path):
    """持有数据目录的跨进程排他锁以防运行实例和离线恢复互相覆盖"""
    directory = directory.resolve()
    directory.parent.mkdir(parents=True, exist_ok=True)
    # 锁文件位于数据目录同级，恢复交换目录时排他锁仍然有效
    with (directory.parent / f".{directory.name}.instance.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise Problem("该数据目录正在使用，请先关闭 Resume Maker。") from exc
        else:
            import fcntl

            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise Problem("该数据目录正在使用，请先关闭 Resume Maker。") from exc
        yield


def create_backup(db: Database, directory: Path) -> Path:
    """冻结业务写事务后备份数据库及登记附件，完整校验成功才发布 ZIP"""
    folder = directory / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = folder / f"{uid()}.db"
    output = snapshot.with_suffix(".zip")
    pending = snapshot.with_suffix(".partial")
    try:
        # 写锁阻止附件删除及登记，独立读连接可在 WAL 模式下执行在线备份
        with db.transaction() as frozen:
            with db.connect() as source, closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
            files = {"resume.db": snapshot}
            for relative in backup_resources(frozen):
                root = directory / relative
                if not root.is_dir():
                    raise Problem(f"备份缺少附件目录：{relative}")
                for file in root.rglob("*"):
                    if any(
                        node.is_symlink() or node.is_junction() for node in (file, *file.parents)
                    ):
                        raise Problem("备份附件包含链接，请先检查数据目录。")
                    if file.is_file():
                        # 模板草稿只包含原件，分页及 CLI 工作区可以重新生成
                        if relative.startswith("template-drafts/"):
                            if file.parent != root or not (
                                file.name == "original.docx" or file.name.startswith("uploaded.")
                            ):
                                continue
                        files[file.relative_to(directory).as_posix()] = file
            checksums = {}
            with ZipFile(pending, "w", ZIP_DEFLATED) as archive:
                for name, file in files.items():
                    digest = hashlib.sha256()
                    size = 0
                    with file.open("rb") as source, archive.open(name, "w") as target:
                        while chunk := source.read(1024 * 1024):
                            target.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    checksums[name] = {"sha256": digest.hexdigest(), "size": size}
                archive.writestr(
                    "backup.json", dump({"version": 2, "created_at": now(), "files": checksums})
                )
        pending.replace(output)
        return output
    finally:
        snapshot.unlink(missing_ok=True)
        pending.unlink(missing_ok=True)


def backup_resources(conn):
    """只枚举已登记且不可变的附件，排除缓存、日志及供应商临时文件"""
    resources = []
    for table in ("templates", "snapshots", "exports"):
        resources.extend(f"{table}/{row[0]}" for row in conn.execute(f"SELECT id FROM {table}"))
    for key, payload in conn.execute(
        "SELECT key,value_json FROM settings WHERE key LIKE 'honor:%' OR key LIKE 'template-task:%'"
    ):
        item = json.loads(payload)
        if key.startswith("honor:") and item.get("attachment"):
            resources.append(f"honors/{item['id']}")
        elif key.startswith("template-task:"):
            resources.append(f"template-drafts/{item['task']['id']}")
    for relative in resources:
        if not re.fullmatch(r"[a-z-]+/[A-Za-z0-9_-]+", relative):
            raise Problem("备份资源标识无效。")
    return resources


def validate_database(path: Path):
    """只读检查备份数据库版本、完整性、外键及模板快照资源"""
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Problem("备份数据库完整性检查失败。")
        if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise Problem("备份版本不受当前程序支持。")
        if conn.execute("PRAGMA foreign_key_check").fetchone():
            raise Problem("备份数据库存在无效引用。")
        for table, file in (("templates", "template.docx"), ("snapshots", "manifest.json")):
            for (identifier,) in conn.execute(f"SELECT id FROM {table}"):
                if not (path.parent / table / identifier / file).is_file():
                    raise Problem(f"备份缺少 {table} 文件：{identifier}")
        for (payload,) in conn.execute("SELECT value_json FROM settings WHERE key LIKE 'honor:%'"):
            item = json.loads(payload)
            attachment = item.get("attachment")
            if not attachment:
                continue
            identifier = item["id"]
            extension = attachment["extension"]
            if str(UUID(identifier)) != identifier or extension not in {
                ".pdf",
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".bmp",
                ".tif",
                ".tiff",
            }:
                raise Problem("备份中的荣誉附件信息无效。")
            folder = path.parent / "honors" / identifier
            files = ["original" + extension] + [
                f"page-{page}.png" for page in range(1, attachment["pages"] + 1)
            ]
            if not all((folder / file).is_file() for file in files):
                raise Problem(f"备份缺少荣誉证书文件：{identifier}")
        for (identifier,) in conn.execute("SELECT id FROM exports"):
            if not all(
                (path.parent / "exports" / identifier / name).is_file()
                for name in ("resume.docx", "manifest.json")
            ):
                raise Problem(f"备份缺少导出文件：{identifier}")
        for (payload,) in conn.execute(
            "SELECT value_json FROM settings WHERE key LIKE 'template-task:%'"
        ):
            item = json.loads(payload)
            folder = path.parent / "template-drafts" / item["task"]["id"]
            if not folder.is_dir() or not any(folder.iterdir()):
                raise Problem("备份缺少模板分析原件。")
            if item["task"]["status"] == "completed" and not (folder / "original.docx").is_file():
                raise Problem("备份缺少已完成模板分析的文档。")


def restore_backup(archive_path: Path, directory: Path) -> Path | None:
    """在隔离目录校验备份，保留旧数据后切换，失败时回退原目录"""
    directory = directory.resolve()
    if directory == Path(directory.anchor) or directory.is_symlink() or directory.is_junction():
        raise Problem("恢复目标必须是独立的普通数据目录。")
    allowed = {
        *FOLDERS,
        "workspaces",
        "backups",
        "logs",
        "template-cache",
        "resume.db",
        "resume.db-wal",
        "resume.db-shm",
        "instance.json",
        ".instance.lock",
        "backup.json",
    }
    with instance_lock(directory):
        if directory.exists() and any(p.name not in allowed for p in directory.iterdir()):
            raise Problem("恢复目录包含非应用文件，请使用独立数据目录。")
        staging = Path(
            tempfile.mkdtemp(prefix=f".{directory.name}-restore-", dir=directory.parent)
        ).resolve()
        previous = None
        try:
            with ZipFile(archive_path.resolve(strict=True)) as archive:
                if sum(i.file_size for i in archive.infolist()) > 2_000_000_000:
                    raise Problem("备份解压大小超过 2 GB。")
                names = set()
                for item in archive.infolist():
                    relative = PurePosixPath(item.filename)
                    if (
                        relative.is_absolute()
                        or ".." in relative.parts
                        or not relative.parts
                        or "\\" in item.filename
                        or ":" in item.filename
                        or relative.parts[0] not in {*FOLDERS, "resume.db", "backup.json"}
                        or (item.external_attr >> 16) & 0o170000 == 0o120000
                    ):
                        raise Problem("备份包含不安全的文件路径。")
                    destination = (staging / Path(*relative.parts)).resolve()
                    if not destination.is_relative_to(staging) or destination in names:
                        raise Problem("备份包含重复或越界路径。")
                    names.add(destination)
                    if item.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(item) as source, destination.open("wb") as target:
                            shutil.copyfileobj(source, target)
            metadata = json.loads((staging / "backup.json").read_text(encoding="utf-8"))
            if metadata.get("version") not in {1, 2}:
                raise Problem("备份格式版本不受支持。")
            if metadata["version"] == 2:
                expected = metadata.get("files", {})
                actual = {
                    p.relative_to(staging).as_posix()
                    for p in staging.rglob("*")
                    if p.is_file() and p != staging / "backup.json"
                }
                if set(expected) != actual or "resume.db" not in expected:
                    raise Problem("备份文件清单不完整。")
                for name, check in expected.items():
                    file = staging / name
                    with file.open("rb") as source:
                        fingerprint = hashlib.file_digest(source, "sha256").hexdigest()
                    if file.stat().st_size != check["size"] or fingerprint != check["sha256"]:
                        raise Problem(f"备份文件校验失败：{name}")
            validate_database(staging / "resume.db")
            # CLI 会话文件不在备份内，恢复后根据已保存消息重新建立上下文
            with closing(sqlite3.connect(staging / "resume.db")) as conn, conn:
                conn.execute("UPDATE conversations SET provider_thread_id=NULL")
                conn.execute(
                    "INSERT OR REPLACE INTO settings VALUES ('workspace-generation', ?)",
                    (dump(uid()),),
                )
                conn.execute(
                    "UPDATE jobs SET status='interrupted',error='从备份恢复，请重新发送任务。' "
                    "WHERE status IN ('running','queued')"
                )
            if directory.exists():
                previous = directory.with_name(f"{directory.name}-before-restore-{uid()[:8]}")
                directory.rename(previous)
            try:
                staging.rename(directory)
            except OSError:
                if previous:
                    previous.rename(directory)
                raise
            return previous
        finally:
            # 只清理已核验的临时解压目录
            if (
                staging.exists()
                and staging.parent == directory.parent
                and staging.name.startswith(f".{directory.name}-restore-")
            ):
                shutil.rmtree(staging)
