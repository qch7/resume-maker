"""Offline recovery uses the same instance lock as the application server."""

import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

from .catalog import Problem
from .db import Database, dump, now, uid

FOLDERS = ("templates", "snapshots", "exports")


@contextmanager
def instance_lock(directory: Path):
    directory = directory.resolve()
    directory.parent.mkdir(parents=True, exist_ok=True)
    # A sibling lock remains held while restore swaps the data directory.
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
    folder = directory / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = folder / f"{uid()}.db"
    output = snapshot.with_suffix(".zip")
    try:
        with db.connect() as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            archive.write(snapshot, "resume.db")
            archive.writestr("backup.json", dump({"version": 1, "created_at": now()}))
            for name in FOLDERS:
                for file in (directory / name).rglob("*"):
                    if file.is_file() and not file.is_symlink() and not file.is_junction():
                        archive.write(file, file.relative_to(directory).as_posix())
        return output
    finally:
        snapshot.unlink(missing_ok=True)


def validate_database(path: Path):
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Problem("备份数据库完整性检查失败。")
        if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise Problem("备份版本不受当前程序支持。")
        if conn.execute("PRAGMA foreign_key_check").fetchone():
            raise Problem("备份数据库存在无效引用。")
        for table, file in (("templates", "template.docx"), ("snapshots", "manifest.json")):
            for (identifier,) in conn.execute(f"SELECT id FROM {table}"):
                if not (path.parent / table / identifier / file).is_file():
                    raise Problem(f"备份缺少 {table} 文件：{identifier}")


def restore_backup(archive_path: Path, directory: Path) -> Path | None:
    directory = directory.resolve()
    if directory == Path(directory.anchor) or directory.is_symlink() or directory.is_junction():
        raise Problem("恢复目标必须是独立的普通数据目录。")
    allowed = {
        *FOLDERS,
        "workspaces",
        "backups",
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
            if metadata.get("version") != 1:
                raise Problem("备份格式版本不受支持。")
            validate_database(staging / "resume.db")
            # CLI session files live outside the backup; rebuild context from saved messages.
            with closing(sqlite3.connect(staging / "resume.db")) as conn, conn:
                conn.execute("UPDATE conversations SET provider_thread_id=NULL")
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
            # Only the verified temporary extraction directory may be removed.
            if (
                staging.exists()
                and staging.parent == directory.parent
                and staging.name.startswith(f".{directory.name}-restore-")
            ):
                shutil.rmtree(staging)
