"""先发布不可变文件再登记引用的插件资源目录"""

import hashlib
import os
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from json import loads
from pathlib import Path, PurePosixPath
from uuid import UUID

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import dump, now, uid
from resume_maker.infrastructure.filesystem import remove_owned_directory


class Assets:
    """文件和数据库分阶段提交，孤立产物留有维护记录"""

    def __init__(self, db, directory: Path):
        """资源统一保存在资料目录，租约仅属于当前应用实例"""
        self.db, self.directory = db, directory
        self.lock, self.leases = threading.RLock(), Counter()
        (directory / "assets").mkdir(parents=True, exist_ok=True)

    def stage(self, owner: str, data: bytes, media_type: str) -> dict:
        """写入本次拥有的暂存文件并落盘，原子移动到不可变位置"""
        identifier = uid()
        root = self.directory / "assets" / identifier
        root.mkdir()
        pending, target = root / "payload.partial", root / "payload"
        record = {
            "id": identifier,
            "owner": owner,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "media_type": media_type,
            "path": target.relative_to(self.directory).as_posix(),
            "state": "staging",
            "references": [],
            "created_at": now(),
        }
        self.db.set_setting(f"asset:{identifier}", record)
        with pending.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        pending.replace(target)
        return record

    def publish(self, conn, staged: dict, references: list[str]) -> dict:
        """在业务事务内核验摘要并登记引用，失败产物保持不可见"""
        row = conn.execute(
            "SELECT value_json FROM settings WHERE key=?", (f"asset:{staged['id']}",)
        ).fetchone()
        if row is None or loads(row[0]) != staged or staged["state"] != "staging":
            raise Problem("资源暂存记录已改变，不能重复发布。", 409)
        path = self.resource_path(staged["id"]) / "payload"
        if staged["path"] != path.relative_to(self.directory).as_posix():
            raise Problem("资源位置不属于当前暂存记录。", 409)
        if hashlib.sha256(path.read_bytes()).hexdigest() != staged["sha256"]:
            raise Problem("资源在发布前发生变化。", 409)
        saved = {**staged, "state": "published", "references": list(references)}
        conn.execute(
            "INSERT OR REPLACE INTO settings VALUES (?,?)", (f"asset:{staged['id']}", dump(saved))
        )
        return saved

    def bundle(self, key, conn=None):
        """逻辑资源名只定位索引，真实文件由不可变资源标识定位"""
        self._logical_path(key)
        if conn is None:
            return self.db.setting(f"asset-bundle:{key}")
        row = conn.execute(
            "SELECT value_json FROM settings WHERE key=?", (f"asset-bundle:{key}",)
        ).fetchone()
        return loads(row[0]) if row else None

    def _logical_path(self, name):
        """逻辑目录和文件必须为规范相对路径且不包含特殊路径分量"""
        path = PurePosixPath(name)
        if (
            not name
            or path.is_absolute()
            or path.as_posix() != name
            or any(part in {".", ".."} for part in path.parts)
            or any(char in name for char in ("\\", ":", "\x00"))
        ):
            raise Problem("资源逻辑路径无效。", 409)
        return path

    def stage_bundle(self, owner, files):
        """暂存完整文件集合，失败时不发布部分文件或业务引用"""
        result, by_digest = {}, {}
        for name, data in files.items():
            self._logical_path(name)
            fingerprint = hashlib.sha256(data).hexdigest()
            if fingerprint not in by_digest:
                by_digest[fingerprint] = self.stage(owner, data, "application/octet-stream")
            result[name] = by_digest[fingerprint]
        return result

    def publish_bundle(self, conn, owner, key, staged):
        """在业务事务内替换完整文件索引并原子转移资源引用"""
        previous = self.bundle(key, conn)
        if previous and previous["owner"] != owner:
            raise Problem("资源集合不属于当前插件。", 403)
        reference = f"bundle:{key}"
        files, published = {}, set()
        for name, record in staged.items():
            self._logical_path(name)
            if record["owner"] != owner:
                raise Problem("暂存资源不属于当前插件。", 403)
            if record["id"] not in published:
                if record["state"] == "published":
                    row = conn.execute(
                        "SELECT value_json FROM settings WHERE key=?", (f"asset:{record['id']}",)
                    ).fetchone()
                    current = loads(row[0]) if row else None
                    if not current or current["state"] != "published" or current["owner"] != owner:
                        raise Problem("资源已失效，不能附接引用。", 409)
                    current["references"] = sorted(set(current["references"]) | {reference})
                    conn.execute(
                        "UPDATE settings SET value_json=? WHERE key=?",
                        (dump(current), f"asset:{record['id']}"),
                    )
                else:
                    self.publish(conn, record, [reference])
                published.add(record["id"])
            files[name] = record["id"]
        if previous:
            for identifier in set(previous["files"].values()) - published:
                self.release_reference(conn, identifier, owner, reference)
        result = {
            "owner": owner,
            "files": files,
            "version": previous["version"] + 1 if previous else 1,
        }
        conn.execute(
            "INSERT OR REPLACE INTO settings VALUES (?,?)", (f"asset-bundle:{key}", dump(result))
        )
        return result

    def update_bundle(self, conn, owner, key, staged):
        """只替换明确更新的文件，其余不可变文件继续复用原资源"""
        previous = self.bundle(key, conn)
        retained = {}
        for name, identifier in (previous or {}).get("files", {}).items():
            if name not in staged:
                row = conn.execute(
                    "SELECT value_json FROM settings WHERE key=?", (f"asset:{identifier}",)
                ).fetchone()
                if row is None:
                    raise Problem("资源集合引用缺失。", 409)
                retained[name] = loads(row[0])
        return self.publish_bundle(conn, owner, key, {**retained, **staged})

    def release_bundle(self, conn, owner, key):
        """解除业务文件集合的全部引用，物理删除仍由维护计划决定"""
        bundle = self.bundle(key, conn)
        if not bundle:
            return
        if bundle["owner"] != owner:
            raise Problem("资源集合不属于当前插件。", 403)
        for identifier in bundle["files"].values():
            self.release_reference(conn, identifier, owner, f"bundle:{key}")
        conn.execute("DELETE FROM settings WHERE key=?", (f"asset-bundle:{key}",))

    def file_id(self, key, name, conn=None):
        """解析已发布集合里的文件，拒绝未登记文件名"""
        self._logical_path(name)
        bundle = self.bundle(key, conn)
        identifier = bundle and bundle["files"].get(name)
        if not identifier:
            raise Problem("文件不存在或尚未发布。", 404)
        return identifier

    @contextmanager
    def open_file(self, key, name):
        """读取期间持有实际资源租约，删除业务记录也不回收在途下载"""
        with self.lock:
            identifier = self.file_id(key, name)
            lease = self.lease(identifier)
            path = lease.__enter__()
        try:
            yield path
        finally:
            lease.__exit__(None, None, None)

    def read_file(self, key, name):
        """在资源租约内返回不可变字节，不泄露可写原件路径"""
        with self.open_file(key, name) as path:
            return path.read_bytes()

    @contextmanager
    def lease(self, identifier: str):
        """读取前核验状态和摘要，释放前阻止清理文件"""
        with self.lock:
            record = self.db.setting(f"asset:{identifier}")
            if not record or record["state"] != "published":
                raise Problem("资源不存在或尚未发布。", 404)
            path = (self.directory / record["path"]).resolve()
            if not path.is_relative_to((self.directory / "assets").resolve()):
                raise Problem("资源位置无效。", 409)
            if not path.is_file():
                raise Problem("资源原件缺失，请从备份恢复。", 409)
            if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                raise Problem("资源摘要不匹配。", 409)
            self.leases[identifier] += 1
        try:
            yield path
        finally:
            with self.lock:
                self.leases[identifier] -= 1

    def tombstone(self, identifier: str, owner: str) -> None:
        """仅无引用资源可以标记待回收，保留文件直到维护操作确认"""
        with self.lock, self.db.transaction() as conn:
            row = conn.execute(
                "SELECT value_json FROM settings WHERE key=?", (f"asset:{identifier}",)
            ).fetchone()
            record = loads(row[0]) if row else None
            if not record or record["owner"] != owner:
                raise Problem("资源不属于当前插件。", 403)
            if record["references"] or self.leases[identifier]:
                raise Problem("资源仍被引用或使用。", 409)
            record["state"] = "tombstone"
            record["retired_at"] = now()
            conn.execute(
                "UPDATE settings SET value_json=? WHERE key=?",
                (dump(record), f"asset:{identifier}"),
            )

    def release_reference(self, conn, identifier: str, owner: str, reference: str) -> None:
        """在删除业务引用的同一事务内解除资源引用，文件仍保留到显式维护"""
        row = conn.execute(
            "SELECT value_json FROM settings WHERE key=?", (f"asset:{identifier}",)
        ).fetchone()
        record = loads(row[0]) if row else None
        if not record or record["owner"] != owner:
            raise Problem("资源不属于当前插件。", 403)
        record["references"] = [item for item in record["references"] if item != reference]
        conn.execute(
            "UPDATE settings SET value_json=? WHERE key=?", (dump(record), f"asset:{identifier}")
        )

    def resource_path(self, identifier: str) -> Path:
        """资源只允许规范 UUID 目录，拒绝路径链接及工作区外目标"""
        try:
            if str(UUID(identifier)) != identifier:
                raise ValueError(identifier)
        except ValueError as exc:
            raise Problem("资源标识无效。", 409) from exc
        root = self.directory / "assets"
        target = root / identifier
        if any(node.is_symlink() or node.is_junction() for node in (target, *target.parents)):
            raise Problem("资源目录包含链接，不能读取或回收。", 409)
        if not target.resolve().is_relative_to(root.resolve()):
            raise Problem("资源位置无效。", 409)
        return target

    def inventory(self, identifier: str) -> list[dict]:
        """回收计划固定文件内容，只处理资源协议拥有的两个文件名"""
        target = self.resource_path(identifier)
        if not target.exists():
            return []
        result = []
        for path in sorted(target.iterdir()):
            if (
                path.name not in {"payload", "payload.partial"}
                or not path.is_file()
                or path.is_symlink()
                or path.is_junction()
            ):
                raise Problem("资源目录含有无法识别的文件，请先检查。", 409)
            result.append(
                {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            )
        return result

    def collection_plan(self, grace_hours: int = 24) -> dict:
        """列出超过保留期的失败暂存、墓碑和无登记目录，已发布资源永不自动回收"""
        if grace_hours < 1:
            raise Problem("资源回收保留期至少为一小时。")
        cutoff = datetime.now(UTC) - timedelta(hours=grace_hours)
        with self.lock, self.db.transaction() as conn:
            records = {
                row["key"].removeprefix("asset:"): loads(row["value_json"])
                for row in conn.execute("SELECT * FROM settings WHERE key LIKE 'asset:%'")
            }
            identifiers = set(records) | {
                path.name for path in (self.directory / "assets").iterdir()
            }
            candidates, blocked = [], []
            for identifier in sorted(identifiers):
                record = records.get(identifier)
                if record and (
                    record["state"] not in {"staging", "tombstone"} or record["references"]
                ):
                    continue
                if self.leases[identifier]:
                    continue
                try:
                    path = self.resource_path(identifier)
                    changed = (
                        datetime.fromisoformat(record.get("retired_at", record["created_at"]))
                        if record
                        else datetime.fromtimestamp(path.stat().st_mtime, UTC)
                    )
                    if changed > cutoff:
                        continue
                    candidates.append(
                        {"id": identifier, "record": record, "files": self.inventory(identifier)}
                    )
                except (Problem, OSError, ValueError) as exc:
                    blocked.append({"id": identifier, "reason": str(exc)})
        plan = {
            "version": 1,
            "directory": str(self.directory.resolve()),
            "created_at": now(),
            "grace_hours": grace_hours,
            "candidates": candidates,
            "blocked": blocked,
        }
        return {**plan, "digest": hashlib.sha256(dump(plan).encode()).hexdigest()}

    def collect(self, plan: dict) -> dict:
        """在备份共用写锁内复核整个计划后回收，失败记录保持可重试"""
        payload = {key: value for key, value in plan.items() if key != "digest"}
        if (
            plan.get("version") != 1
            or plan.get("directory") != str(self.directory.resolve())
            or hashlib.sha256(dump(payload).encode()).hexdigest() != plan.get("digest")
        ):
            raise Problem("资源回收计划无效或不属于当前资料目录。", 409)
        removed = []
        with self.lock, self.db.transaction() as conn:
            for item in plan["candidates"]:
                row = conn.execute(
                    "SELECT value_json FROM settings WHERE key=?", (f"asset:{item['id']}",)
                ).fetchone()
                record = loads(row[0]) if row else None
                if (
                    record != item["record"]
                    or (
                        record
                        and (
                            record["state"] not in {"staging", "tombstone"} or record["references"]
                        )
                    )
                    or self.leases[item["id"]]
                    or self.inventory(item["id"]) != item["files"]
                ):
                    raise Problem("资源在计划生成后已改变或仍在使用，请重新生成计划。", 409)
            for item in plan["candidates"]:
                target = self.resource_path(item["id"])
                if target.exists():
                    remove_owned_directory(self.directory / "assets", target)
                conn.execute("DELETE FROM settings WHERE key=?", (f"asset:{item['id']}",))
                removed.append(item["id"])
        return {"removed": removed, "blocked": plan["blocked"]}
