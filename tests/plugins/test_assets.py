"""资源发布中断、使用租约及显式回收的持久化行为"""

import os
from datetime import UTC, datetime, timedelta

import pytest

from resume_maker.infrastructure.assets import Assets
from resume_maker.infrastructure.database import Database, uid
from resume_maker.infrastructure.storage import create_backup, restore_backup


def retire(assets, record):
    """将合成失败记录移到保留期之前，不等待实际时钟"""
    record = {**record, "created_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()}
    assets.db.set_setting(f"asset:{record['id']}", record)
    return record


def test_collection_retains_published_references_and_removes_failed_staging(tmp_path):
    """发布失败及进程崩溃目录可回收，已发布资料和备份恢复仍完整"""
    directory = tmp_path / "data"
    assets = Assets(Database(directory / "resume.db"), directory)
    staged = assets.stage("example", b"failed", "text/plain")
    retire(assets, staged)
    published = assets.stage("example", b"keep", "text/plain")
    with assets.db.transaction() as conn:
        assets.publish(conn, published, ["synthetic:one"])
    orphan = directory / "assets" / uid()
    orphan.mkdir()
    (orphan / "payload.partial").write_bytes(b"interrupted")
    old = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    os.utime(orphan, (old, old))
    plan = assets.collection_plan()
    assert {row["id"] for row in plan["candidates"]} == {staged["id"], orphan.name}
    result = assets.collect(plan)
    assert set(result["removed"]) == {staged["id"], orphan.name}
    with assets.lease(published["id"]) as file:
        assert file.read_bytes() == b"keep"
    backup = create_backup(assets.db, directory)
    restored = tmp_path / "restored"
    restore_backup(backup, restored)
    recovered = Assets(Database(restored / "resume.db"), restored)
    with recovered.lease(published["id"]) as file:
        assert file.read_bytes() == b"keep"


def test_collection_rejects_changed_plan_before_deleting_any_files(tmp_path):
    """候选资源变更会使整个旧计划失效，不先删除其他仍匹配的目录"""
    assets = Assets(Database(tmp_path / "resume.db"), tmp_path)
    records = [
        retire(assets, assets.stage("example", value, "text/plain")) for value in (b"a", b"b")
    ]
    plan = assets.collection_plan()
    with assets.db.transaction() as conn:
        assets.publish(conn, records[1], ["new:reference"])
    with pytest.raises(Exception, match="已改变"):
        assets.collect(plan)
    assert all((tmp_path / row["path"]).exists() for row in records)


def test_tombstone_waits_for_reference_release_and_actual_reader_exit(tmp_path):
    """事务回滚保留引用，正在读取的资源不可退休，重复发布也被拒绝"""
    assets = Assets(Database(tmp_path / "resume.db"), tmp_path)
    staged = assets.stage("example", b"content", "text/plain")
    with assets.db.transaction() as conn:
        assets.publish(conn, staged, ["example:one"])
    with pytest.raises(Exception, match="重复发布"), assets.db.transaction() as conn:
        assets.publish(conn, staged, [])
    with pytest.raises(RuntimeError), assets.db.transaction() as conn:
        assets.release_reference(conn, staged["id"], "example", "example:one")
        raise RuntimeError("rollback")
    with pytest.raises(Exception, match="仍被引用"):
        assets.tombstone(staged["id"], "example")
    with assets.db.transaction() as conn:
        assets.release_reference(conn, staged["id"], "example", "example:one")
    with assets.lease(staged["id"]):
        with pytest.raises(Exception, match="仍被引用"):
            assets.tombstone(staged["id"], "example")
    assets.tombstone(staged["id"], "example")
    assert assets.collection_plan()["candidates"] == []
    record = assets.db.setting(f"asset:{staged['id']}")
    record["retired_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    assets.db.set_setting(f"asset:{staged['id']}", record)
    assert assets.collect(assets.collection_plan())["removed"] == [staged["id"]]
