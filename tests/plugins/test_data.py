"""插件缺包、停用和失败升级时的数据保护行为"""

import json
import sqlite3

import pytest

from resume_maker.infrastructure.data_maintenance import DataMaintenance
from resume_maker.infrastructure.database import Database, dump
from resume_maker.infrastructure.storage import restore_backup
from resume_maker.sdk.manifest import Manifest


def test_incompatible_optional_data_blocks_feature_and_preserves_minimal_host(tmp_path):
    """可选插件资料过新时保留其原数据，重启仍能编辑系统资料且代次稳定"""
    from resume_maker.api import create_app
    from resume_maker.core.config import Config
    from resume_maker.plugins.discovery import selection
    from resume_maker.sdk.context import ServiceKey

    selected = selection("minimal")[1] | {"ext.recruitment"}
    app = create_app(Config(data_dir=tmp_path, plugins=tuple(selected)))
    db = app.state.runtime.require(ServiceKey("db"))
    with db.transaction() as conn:
        conn.execute(
            "UPDATE plugin_data_catalog SET schema_version=2 WHERE plugin_id='ext.recruitment'"
        )
        conn.execute("INSERT INTO settings VALUES ('recruitment-bookmarks', '{}')")
    generation = app.state.runtime.generation
    app.state.runtime.close()
    for _ in range(2):
        app = create_app(Config(data_dir=tmp_path))
        host = app.state.runtime
        try:
            assert "ext.recruitment" in host.desired and "ext.recruitment" not in host.selected
            assert "资料版本 2" in host.blocked["ext.recruitment"]
            assert host.generation == generation + 1
            assert host.require(ServiceKey("db")).setting("recruitment-bookmarks") == {}
            assert host.require(ServiceKey("catalog")).create_project("合成手工资料", [])["id"]
        finally:
            host.close()


def migration_fixture(tmp_path, statements):
    """建立命名空间表和附件，迁移只接触合成数据"""
    directory = tmp_path / "data"
    db = Database(directory / "resume.db")
    descriptor = {
        "tables": ["plugin_community_example_items"],
        "folders": ["plugin-data/community.example"],
    }
    with db.transaction() as conn:
        conn.execute("CREATE TABLE plugin_community_example_items(id TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO plugin_community_example_items VALUES ('one','before')")
        conn.execute(
            "INSERT INTO plugin_data_catalog VALUES (?,?,?,?)",
            ("community.example", 1, dump(descriptor), "1.0.0"),
        )
    folder = directory / "plugin-data" / "community.example"
    folder.mkdir(parents=True)
    (folder / "original.txt").write_text("synthetic", encoding="utf-8")
    location = tmp_path / "verified-package"
    location.mkdir()
    (location / "migration.json").write_text(
        dump({"version": 1, "from": 1, "to": 2, "sql": statements}), encoding="utf-8"
    )
    manifest = Manifest(
        id="community.example",
        version="2.0.0",
        title="合成插件",
        package="example",
        data={
            **descriptor,
            "schema_version": 2,
            "reads": [1, 2],
            "writes": [2],
            "migrations": ["migration.json"],
        },
    )
    return DataMaintenance(db, directory), manifest, location


def test_plugin_migration_keeps_restorable_snapshot_and_namespaced_attachments(tmp_path):
    """副本成功后才切换版本，旧 ZIP 无需插件代码也能恢复附件及旧资料"""
    coordinator, manifest, location = migration_fixture(
        tmp_path,
        [
            "ALTER TABLE plugin_community_example_items ADD COLUMN checked INTEGER DEFAULT 1",
            "UPDATE plugin_community_example_items SET value='after'",
        ],
    )
    plan = coordinator.plan(manifest, location)
    result = coordinator.apply(plan, manifest, location)
    assert result["state"] == "committed"
    assert coordinator.db.one("SELECT * FROM plugin_community_example_items") == {
        "id": "one",
        "value": "after",
        "checked": 1,
    }
    assert (
        coordinator.db.one(
            "SELECT schema_version FROM plugin_data_catalog WHERE plugin_id=?", (manifest.id,)
        )["schema_version"]
        == 2
    )
    from pathlib import Path

    restored = tmp_path / "restored"
    restore_backup(Path(result["backup"]), restored)
    original = Database(restored / "resume.db")
    assert original.one("SELECT value FROM plugin_community_example_items")["value"] == "before"
    assert (restored / "plugin-data/community.example/original.txt").read_text(
        encoding="utf-8"
    ) == "synthetic"


def test_failed_or_cross_owner_migration_never_changes_original(tmp_path):
    """越权 SQL 在副本被拒绝，原库、附件和版本保持可用"""
    coordinator, manifest, location = migration_fixture(
        tmp_path,
        [
            "UPDATE plugin_community_example_items SET value='changed'",
            "DELETE FROM projects",
        ],
    )
    plan = coordinator.plan(manifest, location)
    with pytest.raises(sqlite3.DatabaseError):
        coordinator.apply(plan, manifest, location)
    assert (
        coordinator.db.one("SELECT value FROM plugin_community_example_items")["value"] == "before"
    )
    journals = list((coordinator.directory / "backups/migrations").glob("*/operation.json"))
    assert json.loads(journals[0].read_text(encoding="utf-8"))["state"] == "failed"


def test_migration_plan_rejects_data_changed_after_review(tmp_path):
    """确认的是精确资料和迁移摘要，旧计划不能覆盖后续编辑"""
    coordinator, manifest, location = migration_fixture(tmp_path, [])
    plan = coordinator.plan(manifest, location)
    coordinator.db.set_setting("community.example:later", {"saved": True})
    with pytest.raises(Exception, match="已改变"):
        coordinator.apply(plan, manifest, location)


def test_new_plugin_schema_initializes_only_in_explicit_maintenance(tmp_path):
    """新插件从零迁移私有表，首次激活不能声称不存在的表已初始化"""
    coordinator, manifest, location = migration_fixture(tmp_path, [])
    with coordinator.db.transaction() as conn:
        conn.execute("DROP TABLE plugin_community_example_items")
        conn.execute("DELETE FROM plugin_data_catalog WHERE plugin_id=?", (manifest.id,))
    manifest = manifest.model_copy(
        update={
            "data": manifest.data.model_copy(
                update={
                    "schema_version": 1,
                    "writes": [1],
                    "reads": [1],
                }
            )
        }
    )
    (location / "migration.json").write_text(
        dump(
            {
                "version": 1,
                "from": 0,
                "to": 1,
                "sql": ["CREATE TABLE plugin_community_example_items(id TEXT PRIMARY KEY)"],
            }
        ),
        encoding="utf-8",
    )
    plan = coordinator.plan(manifest, location)
    assert plan["from"] == 0
    coordinator.apply(plan, manifest, location)
    assert coordinator.db.all("SELECT * FROM plugin_community_example_items") == []


def test_schema_upgrade_preserves_removed_attachment_ownership(tmp_path):
    """新清单删去附件目录声明仍保留历史目录归属，备份不静默丢原件"""
    coordinator, manifest, location = migration_fixture(tmp_path, [])
    manifest = manifest.model_copy(
        update={"data": manifest.data.model_copy(update={"folders": []})}
    )
    coordinator.apply(coordinator.plan(manifest, location), manifest, location)
    record = coordinator.db.one(
        "SELECT descriptor_json FROM plugin_data_catalog WHERE plugin_id=?", (manifest.id,)
    )
    assert "plugin-data/community.example" in record["descriptor"]["folders"]
