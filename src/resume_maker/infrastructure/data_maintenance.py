"""在停机副本执行命名空间数据迁移，校验成功才原子替换工作库"""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import PurePosixPath

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.data_catalog import validate_descriptor
from resume_maker.infrastructure.database import dump, now, uid
from resume_maker.infrastructure.storage import create_backup


def digest(value):
    """对计划数据生成稳定摘要，确认后任意内容变化都会失效"""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class DataMaintenance:
    """维护入口不启动插件业务、模型、前端或任务"""

    def __init__(self, db, directory):
        """调用方必须持有工作区实例锁，迁移只作用于已验证插件私有资料"""
        self.db, self.directory = db, directory

    def plan(self, manifest, location):
        """列出版本路径、包摘要和数据库基线，缺少任何一步均拒绝升级"""
        if manifest.data is None:
            raise Problem("插件没有持久资料声明。", 409)
        descriptor = manifest.data.model_dump()
        validate_descriptor(manifest.id, descriptor, True)
        with self.db.connect() as conn:
            current = conn.execute(
                "SELECT schema_version FROM plugin_data_catalog WHERE plugin_id=?", (manifest.id,)
            ).fetchone()
            version = current[0] if current else 0
            baseline = hashlib.sha256(conn.serialize()).hexdigest()
        target = manifest.data.schema_version
        if version > target or target not in manifest.data.writes:
            raise Problem("目标代码不能写入当前资料，回退需要完整恢复点。", 409)
        available, steps = {}, []
        for name in manifest.data.migrations:
            path = self._file(location, name)
            data = path.read_bytes()
            step = json.loads(data)
            if (
                step.get("version") != 1
                or step.get("to") != step.get("from", -1) + 1
                or step["from"] in available
            ):
                raise Problem("插件迁移路径重复或不连续。", 409)
            available[step["from"]] = {
                "file": name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "from": step["from"],
                "to": step["to"],
            }
        cursor = version
        while cursor < target:
            if cursor not in available:
                raise Problem(f"缺少从版本 {cursor} 开始的数据迁移。", 409)
            steps.append(available[cursor])
            cursor += 1
        plan = {
            "version": 1,
            "owner": manifest.id,
            "package_version": manifest.version,
            "package_digest": location.name,
            "database_hash": baseline,
            "from": version,
            "to": target,
            "steps": steps,
            "data_policy": "backup-and-copy",
        }
        return {**plan, "digest": digest(plan)}

    def _file(self, location, name):
        """维护文件只从已验证包读取，备份中的资料不会被解释为代码"""
        relative = PurePosixPath(name)
        path = location.joinpath(*relative.parts)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != name
            or path.suffix != ".json"
            or path.is_symlink()
            or not path.resolve().is_relative_to(location)
        ):
            raise Problem("插件迁移文件位置无效。", 409)
        return path

    def apply(self, approved, manifest, location):
        """先完整备份，再于独立数据库迁移，失败保留原库和可查询记录"""
        current = self.plan(manifest, location)
        if current != approved:
            raise Problem("资料或插件已改变，请停止应用后重新生成迁移计划。", 409)
        if not current["steps"]:
            return {"state": "unchanged", "version": current["to"]}
        backup = create_backup(self.db, self.directory)
        identifier = uid()
        root = self.directory / "backups" / "migrations" / identifier
        root.mkdir(parents=True)
        candidate = root / "candidate.db"
        journal = root / "operation.json"
        record = {
            "id": identifier,
            "plan": current,
            "backup": str(backup),
            "created_at": now(),
            "state": "preparing",
        }
        journal.write_text(dump(record), encoding="utf-8")
        with self.db.connect() as source, closing(sqlite3.connect(candidate)) as target:
            source.backup(target)
        try:
            with closing(sqlite3.connect(candidate)) as conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
                for step in current["steps"]:
                    payload = json.loads(
                        self._file(location, step["file"]).read_text(encoding="utf-8")
                    )
                    self._step(conn, manifest, payload)
                descriptor = manifest.data.model_dump()
                if descriptor.get("descriptor"):
                    descriptor.update(
                        json.loads(
                            self._file(location, descriptor["descriptor"]).read_text(
                                encoding="utf-8"
                            )
                        )
                    )
                validate_descriptor(manifest.id, descriptor, True)
                previous = conn.execute(
                    "SELECT descriptor_json FROM plugin_data_catalog WHERE plugin_id=?",
                    (manifest.id,),
                ).fetchone()
                if previous:
                    descriptor["folders"] = sorted(
                        set(descriptor.get("folders", []))
                        | set(json.loads(previous[0]).get("folders", []))
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO plugin_data_catalog VALUES (?,?,?,?)",
                    (manifest.id, current["to"], dump(descriptor), manifest.version),
                )
                if (
                    conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or conn.execute("PRAGMA foreign_key_check").fetchone()
                ):
                    raise Problem("迁移副本的数据库或引用校验失败。", 409)
                conn.commit()
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("PRAGMA journal_mode=DELETE")
            with self.db.connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            candidate.replace(self.db.path)
            record["state"] = "committed"
            try:
                journal.write_text(dump(record), encoding="utf-8")
            except OSError:
                # 数据库替换已提交，日志失败不能报告为原库保持不变
                pass
            return {
                "id": identifier,
                "state": "committed",
                "version": current["to"],
                "backup": str(backup),
            }
        except BaseException as exc:
            record.update(state="failed", error=type(exc).__name__)
            journal.write_text(dump(record), encoding="utf-8")
            raise

    def _step(self, conn, manifest, payload):
        """SQL 仅能访问声明的私有表，设置转换通过受限键值命令执行"""
        tables = set(manifest.data.tables)

        def authorize(action, first, second, _database, _trigger):
            """SQLite 自身校验每项表操作，禁止附加数据库、扩展和任意 PRAGMA"""
            if action in {
                sqlite3.SQLITE_ATTACH,
                sqlite3.SQLITE_DETACH,
                sqlite3.SQLITE_PRAGMA,
                sqlite3.SQLITE_TRANSACTION,
                sqlite3.SQLITE_SAVEPOINT,
                sqlite3.SQLITE_DROP_VIEW,
                sqlite3.SQLITE_DROP_TEMP_VIEW,
                sqlite3.SQLITE_DROP_TRIGGER,
                sqlite3.SQLITE_DROP_TEMP_TRIGGER,
                sqlite3.SQLITE_CREATE_TEMP_TABLE,
                sqlite3.SQLITE_DROP_TEMP_TABLE,
                sqlite3.SQLITE_CREATE_TEMP_INDEX,
                sqlite3.SQLITE_DROP_TEMP_INDEX,
                sqlite3.SQLITE_CREATE_TRIGGER,
                sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
                sqlite3.SQLITE_CREATE_VIEW,
                sqlite3.SQLITE_CREATE_TEMP_VIEW,
                sqlite3.SQLITE_CREATE_VTABLE,
                sqlite3.SQLITE_DROP_VTABLE,
            }:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION and (second or "").lower() == "load_extension":
                return sqlite3.SQLITE_DENY
            if action in {
                sqlite3.SQLITE_READ,
                sqlite3.SQLITE_INSERT,
                sqlite3.SQLITE_UPDATE,
                sqlite3.SQLITE_DELETE,
                sqlite3.SQLITE_CREATE_TABLE,
                sqlite3.SQLITE_DROP_TABLE,
            }:
                if first not in tables | {"sqlite_master", "sqlite_schema"}:
                    return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_ALTER_TABLE and second not in tables:
                return sqlite3.SQLITE_DENY
            if (
                action in {sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_DROP_INDEX}
                and second not in tables
            ):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        conn.set_authorizer(authorize)
        try:
            for statement in payload.get("sql", []):
                if not isinstance(statement, str) or len(statement) > 65536:
                    raise Problem("迁移 SQL 格式无效。", 409)
                conn.execute(statement)
        finally:
            conn.set_authorizer(None)
        for operation in payload.get("settings", []):
            if not operation["key"].startswith(manifest.id + ":"):
                raise Problem("迁移不能写入其他所有者的设置。", 409)
            conn.execute(
                "INSERT OR REPLACE INTO settings VALUES (?,?)",
                (operation["key"], dump(operation["value"])),
            )
