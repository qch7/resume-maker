"""离线恢复和应用服务器共用实例锁以免数据目录被并发覆盖"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.data_catalog import resource_records
from resume_maker.infrastructure.database import SCHEMA_VERSION, Database, dump, now, uid
from resume_maker.infrastructure.filesystem import publish_directory

FOLDERS = ("assets", "plugin-data")


@contextmanager
def instance_lock(directory: Path):
    """持有数据目录的跨进程排他锁以防运行实例和离线恢复互相覆盖"""
    directory = directory.resolve()
    lock_directory = directory.parent
    if (lock_directory / "pyproject.toml").is_file():
        lock_directory = lock_directory / ".local" / "locks"
    lock_directory.mkdir(parents=True, exist_ok=True)
    # 锁保存在数据目录外，源码运行集中到 .local，恢复交换目录时排他锁继续有效
    with (lock_directory / f".{directory.name}.instance.lock").open("a+b") as lock:
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
    """短事务固定读取快照和附件副本，释放写锁后复制数据库及压缩"""
    folder = directory / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = folder / f"{uid()}.db"
    output = snapshot.with_suffix(".zip")
    pending = snapshot.with_suffix(".partial")
    try:
        with tempfile.TemporaryDirectory(prefix="backup-frozen-", dir=folder) as frozen_dir:
            frozen_root = Path(frozen_dir)
            with db.connect() as source, closing(sqlite3.connect(snapshot)) as target:
                wal = source.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
                with db.transaction():
                    source.execute("BEGIN")
                    source.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
                    files = freeze_backup_files(source, directory, frozen_root)
                    if not wal:
                        # 离线迁移副本的读锁须在写事务提交前释放
                        source.backup(target)
                        source.rollback()
                if wal:
                    source.backup(target)
            files["resume.db"] = snapshot
            with closing(sqlite3.connect(snapshot)) as frozen:
                validate_assets(frozen, frozen_root)
            write_backup_zip(pending, files)
        pending.replace(output)
        return output
    finally:
        snapshot.unlink(missing_ok=True)
        pending.unlink(missing_ok=True)


def freeze_backup_files(conn, directory, frozen_root):
    """不可变附件用硬链接固定生命周期，可变插件文件在写锁内复制"""
    files = {}
    if (directory / "plugins.json").is_file():
        target = frozen_root / "plugins.json"
        shutil.copyfile(directory / "plugins.json", target)
        files["plugins.json"] = target
    for resource in resource_records(conn):
        relative = resource["path"]
        root = directory / relative
        if not root.is_dir():
            if resource.get("optional"):
                continue
            raise Problem(f"备份缺少附件目录：{relative}")
        for file in root.rglob("*"):
            if any(node.is_symlink() or node.is_junction() for node in (file, *file.parents)):
                raise Problem("备份附件包含链接，请先检查数据目录。")
            if file.is_file():
                if not any(
                    fnmatchcase(file.relative_to(root).as_posix(), pattern)
                    for pattern in resource["files"]
                ):
                    continue
                name = file.relative_to(directory).as_posix()
                target = frozen_root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if name in files:
                    continue
                if name.startswith("assets/"):
                    try:
                        os.link(file, target)
                    except OSError:
                        shutil.copyfile(file, target)
                else:
                    shutil.copyfile(file, target)
                files[name] = target
    return files


def write_backup_zip(pending, files):
    """压缩只读取固定副本，不再持有业务数据库写锁"""
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


def validate_database(path: Path):
    """只读检查备份数据库版本、完整性、外键及模板快照资源"""
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Problem("备份数据库完整性检查失败。")
        if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise Problem("备份版本不受当前程序支持。")
        if conn.execute("PRAGMA foreign_key_check").fetchone():
            raise Problem("备份数据库存在无效引用。")
        validate_assets(conn, path.parent)
        for table, name in (("templates", "template.docx"), ("snapshots", "manifest.json")):
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                continue
            for (identifier,) in conn.execute(f"SELECT id FROM {table}"):
                if not stored_file(conn, path.parent, f"{table}/{identifier}", name).is_file():
                    raise Problem(f"备份缺少 {table} 文件：{identifier}")
        for (payload,) in conn.execute("SELECT value_json FROM settings WHERE key LIKE 'honor:%'"):
            item = json.loads(payload)
            attachment = item.get("attachment")
            if not attachment:
                continue
            identifier, extension = item["id"], attachment["extension"]
            if (
                str(UUID(identifier)) != identifier
                or not isinstance(extension, str)
                or not re.fullmatch(r"\.[a-z0-9]{1,16}", extension)
                or type(attachment["pages"]) is not int
                or not 1 <= attachment["pages"] <= 12
            ):
                raise Problem("备份中的荣誉附件信息无效。")
            names = ["original" + extension] + [
                f"page-{page}.png" for page in range(1, attachment["pages"] + 1)
            ]
            files = {
                name: stored_file(conn, path.parent, f"honors/{identifier}", name) for name in names
            }
            if not all(file.is_file() for file in files.values()):
                raise Problem(f"备份缺少荣誉证书文件：{identifier}")
            trace = attachment.get("importer")
            if trace is not None and (
                not isinstance(trace, dict)
                or trace.get("pages") != attachment["pages"]
                or hashlib.sha256(files["original" + extension].read_bytes()).hexdigest()
                != trace.get("source_sha256")
            ):
                raise Problem("证书原件与导入记录不一致，恢复已停止。")
        for identifier, raw in conn.execute("SELECT id,manifest_json FROM exports"):
            bundle = conn.execute(
                "SELECT value_json FROM settings WHERE key=?",
                (f"asset-bundle:exports/{identifier}",),
            ).fetchone()
            if not bundle:
                raise Problem(f"备份缺少导出资源：{identifier}")
            files = json.loads(bundle[0])["files"]
            if "resume.docx" not in files or json.loads(raw).get("assets") != files:
                raise Problem("导出资源和成品追溯不一致。")
        for (payload,) in conn.execute(
            "SELECT value_json FROM settings WHERE key LIKE 'template-task:%'"
        ):
            item = json.loads(payload)
            key = f"template-drafts/{item['task']['id']}"
            bundle = conn.execute(
                "SELECT value_json FROM settings WHERE key=?", (f"asset-bundle:{key}",)
            ).fetchone()
            if not bundle or not json.loads(bundle[0])["files"]:
                raise Problem("备份缺少模板分析原件。")
            if (
                item["task"]["status"] == "completed"
                and not stored_file(conn, path.parent, key, "original.docx").is_file()
            ):
                raise Problem("备份缺少已完成模板分析的文档。")


def stored_file(conn, directory, key, name):
    """离线校验通过持久资源索引定位必要附件"""
    logical = PurePosixPath(key) / name
    if logical.is_absolute() or ".." in logical.parts or "\\" in str(logical):
        raise Problem("备份资源位置无效。")
    row = conn.execute(
        "SELECT value_json FROM settings WHERE key=?", (f"asset-bundle:{key}",)
    ).fetchone()
    if row is None:
        raise Problem("备份缺少资源集合。")
    identifier = json.loads(row[0])["files"].get(name)
    if not identifier:
        raise Problem("备份资源集合缺少必要文件。")
    return directory / "assets" / identifier / "payload"


def validate_assets(conn, directory):
    """数据库记录和文件清单同时校验，不能只验证 ZIP 内部自洽"""
    for key, raw in conn.execute(
        "SELECT key,value_json FROM settings WHERE key LIKE 'asset-bundle:%'"
    ):
        bundle = json.loads(raw)
        for name, identifier in bundle["files"].items():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or path.as_posix() != name or "\\" in name:
                raise Problem("资源集合文件名无效。")
            row = conn.execute(
                "SELECT value_json FROM settings WHERE key=?", (f"asset:{identifier}",)
            ).fetchone()
            resource = json.loads(row[0]) if row else None
            reference = "bundle:" + key.removeprefix("asset-bundle:")
            if (
                not resource
                or resource["state"] != "published"
                or resource["owner"] != bundle["owner"]
                or reference not in resource["references"]
            ):
                raise Problem("资源集合引用无效，恢复已停止。")
    for (raw,) in conn.execute("SELECT value_json FROM settings WHERE key LIKE 'asset:%'"):
        record = json.loads(raw)
        if record["state"] != "published":
            continue
        expected = f"assets/{record['id']}/payload"
        if record["path"] != expected or str(UUID(record["id"])) != record["id"]:
            raise Problem("资源目录册路径无效。")
        path = directory / expected
        if not path.is_file() or path.stat().st_size != record["size"]:
            raise Problem("备份缺少已发布资源或资源大小不匹配。")
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise Problem("已发布资源摘要不匹配。")
        if not isinstance(record.get("references"), list):
            raise Problem("资源引用格式无效。")


def restore_backup(archive_path: Path, directory: Path) -> Path | None:
    """在隔离目录校验备份，保留旧数据后切换，失败时回退原目录"""
    directory = directory.resolve()
    if directory == Path(directory.anchor) or directory.is_symlink() or directory.is_junction():
        raise Problem("恢复目标必须是独立的普通数据目录。")
    allowed = {
        *FOLDERS,
        "templates",
        "snapshots",
        "exports",
        "honors",
        "template-drafts",
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
        "plugins.json",
        "plugins-operation.json",
        "plugin-operations",
        "plugin-packages",
        "plugin-packages.json",
        "plugin-environments",
        "plugin-environments.json",
        "plugin-pins.json",
        "plugin-downloads",
        "plugin-trials",
        "plugin-migrations",
        "credential-vault",
        "host-transition.json",
        "host-runtime.json",
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
                        or relative.parts[0]
                        not in {*FOLDERS, "resume.db", "backup.json", "plugins.json"}
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
            if metadata.get("version") != 2:
                raise Problem("备份格式版本不受支持。")
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
                tables = {
                    row[0]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "conversations" in tables:
                    conn.execute("UPDATE conversations SET provider_thread_id=NULL")
                conn.execute(
                    "INSERT OR REPLACE INTO settings VALUES ('workspace-generation', ?)",
                    (dump(uid()),),
                )
                if "jobs" in tables:
                    conn.execute(
                        "UPDATE jobs SET status='interrupted',error='从备份恢复，请重新发送任务。' "
                        "WHERE status IN ('running','queued')"
                    )
            vault = directory / "credential-vault"
            if vault.exists():
                if (
                    vault.is_symlink()
                    or vault.is_junction()
                    or any(path.is_symlink() or path.is_junction() for path in vault.rglob("*"))
                ):
                    raise Problem("凭据目录不能包含符号链接。")
                shutil.copytree(vault, staging / "credential-vault")
            if directory.exists():
                previous = directory.with_name(f"{directory.name}-before-restore-{uid()[:8]}")
                publish_directory(directory, previous)
            try:
                publish_directory(staging, directory)
            except OSError:
                if previous:
                    publish_directory(previous, directory)
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
