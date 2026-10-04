"""旧附件目录迁移到统一资源，先完整备份再发布索引和移除旧副本"""

import hashlib
from json import loads
from pathlib import Path

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.data_catalog import resource_records
from resume_maker.infrastructure.storage import create_backup
from resume_maker.sdk.records import dump, now

ROOTS = {"templates", "template-drafts", "honors", "exports", "snapshots"}


def inventory(directory, key):
    """固定旧附件的内容，拒绝链接和应用目录外的迁移目标"""
    root = directory / key
    if not root.resolve().is_relative_to(directory.resolve()) or len(Path(key).parts) != 2:
        raise Problem("附件迁移位置无效。", 409)
    files = {}
    if not root.exists():
        return files
    for path in [root, *root.rglob("*")]:
        if any(node.is_symlink() or node.is_junction() for node in (path, *path.parents)):
            raise Problem("附件迁移遇到链接，请先检查原目录。", 409)
        if path.is_file():
            files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def remove_legacy(directory, record):
    """完整核验后只移除本次迁移记录里的旧副本，异常可在下次启动继续"""
    root = directory / record["key"]
    current = inventory(directory, record["key"])
    if any(record["files"].get(name) != value for name, value in current.items()):
        raise Problem("迁移后的旧附件发生变化，统一资源和旧副本均已保留。", 409)
    for name in current:
        (root / name).unlink()
    if root.exists():
        for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_dir():
                path.rmdir()
        root.rmdir()


def migrate_legacy_assets(assets):
    """在业务插件启动前迁移已登记原件，失败不删除尚未发布的资料"""
    db, directory = assets.db, assets.directory
    with db.connect() as conn:
        resources = [item for item in resource_records(conn) if item["path"].split("/")[0] in ROOTS]
    pending = [
        {"key": item["path"], "owner": item["owner"], "files": inventory(directory, item["path"])}
        for item in resources
    ]
    pending = [item for item in pending if item["files"]]
    backup = str(create_backup(db, directory)) if pending else None
    migrated = []
    for item in pending:
        root = directory / item["key"]
        reused, original_manifest = reusable_export(assets, item)
        staged = {
            **reused,
            **assets.stage_bundle(
                item["owner"],
                {
                    name: (root / name).read_bytes()
                    for name in item["files"]
                    if name not in reused
                    and not (item["key"].startswith("exports/") and name == "manifest.json")
                },
            ),
        }
        with db.transaction() as conn:
            if inventory(directory, item["key"]) != item["files"] or assets.bundle(
                item["key"], conn
            ):
                raise Problem("附件在迁移准备后发生变化，原件已保留，请重启后重试。", 409)
            # 旧导出曾同时持有目录文件和资源副本，核验后复用已发布资源
            if item["key"].startswith("exports/"):
                identifier = item["key"].split("/")[1]
                row = conn.execute(
                    "SELECT manifest_json FROM exports WHERE id=?", (identifier,)
                ).fetchone()
                manifest = loads(row[0])
                if manifest != original_manifest:
                    raise Problem("导出清单在迁移期间发生变化，原件已保留。", 409)
                manifest["assets"] = {name: record["id"] for name, record in staged.items()}
                conn.execute(
                    "UPDATE exports SET manifest_json=? WHERE id=?", (dump(manifest), identifier)
                )
            assets.publish_bundle(conn, item["owner"], item["key"], staged)
            report = {**item, "backup": backup, "state": "published", "created_at": now()}
            conn.execute(
                "INSERT OR REPLACE INTO settings VALUES (?,?)",
                (f"asset-migration:{item['key']}", dump(report)),
            )
        migrated.append(item["key"])
    # 提交后退出或清理中断都从持久记录恢复，不再次复制已经发布的文件
    for row in db.all("SELECT key,value_json FROM settings WHERE key LIKE 'asset-migration:%'"):
        record = row["value"]
        if record["state"] != "published":
            continue
        bundle = assets.bundle(record["key"])
        if not bundle:
            raise Problem("迁移资源索引缺失，旧副本已保留。", 409)
        expected = {
            name: digest
            for name, digest in record["files"].items()
            if not (record["key"].startswith("exports/") and name == "manifest.json")
        }
        if set(bundle["files"]) != set(expected):
            raise Problem("迁移资源集合和原件清单不一致，旧副本已保留。", 409)
        for name in bundle["files"]:
            if hashlib.sha256(assets.read_file(record["key"], name)).hexdigest() != expected[name]:
                raise Problem("迁移资源和原件摘要不一致，旧副本已保留。", 409)
        remove_legacy(directory, record)
        db.set_setting(row["key"], {**record, "state": "complete", "completed_at": now()})
    return {"migrated": migrated, "backup": backup}


def reusable_export(assets, item):
    """暂存前核验旧导出的资源副本，避免先复制后产生多余暂存"""
    if not item["key"].startswith("exports/"):
        return {}, None
    identifier = item["key"].split("/")[1]
    manifest = assets.db.one("SELECT manifest_json FROM exports WHERE id=?", (identifier,))[
        "manifest"
    ]
    reused = {}
    for name, resource_id in manifest.get("assets", {}).items():
        record = assets.db.setting(f"asset:{resource_id}")
        if (
            name in item["files"]
            and record
            and record["owner"] == item["owner"]
            and record["sha256"] == item["files"][name]
            and record["state"] == "published"
        ):
            with assets.lease(resource_id):
                reused[name] = record
    return reused, manifest
