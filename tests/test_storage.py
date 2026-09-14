"""test_storage.py：模块职责与调用关系见 docs/architecture.md。"""

from zipfile import ZipFile

import pytest

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import Database
from resume_maker.infrastructure.storage import create_backup, instance_lock, restore_backup
from resume_maker.services.catalog import Catalog


def test_restore_preserves_previous_data_and_drafts(catalog, project, populated, tmp_path):
    """验证备份恢复保留旧数据副本和已保存的输入草稿。"""
    p, revision = project["id"], populated["id"]
    point = populated["content"]["highlights"][0]
    catalog.put_draft(p, revision, "highlight:one", {**point, "text": "pending text"}, 0)
    backup = create_backup(catalog.db, catalog.db.path.parent)
    target = tmp_path / "restored"
    target.mkdir()
    (target / "instance.json").write_text("old instance")
    previous = restore_backup(backup, target)
    assert (previous / "instance.json").read_text() == "old instance"
    restored = Catalog(Database(target / "resume.db"))
    assert restored.working(p, revision)["content"]["highlights"][0]["text"] == "pending text"
    assert len(restored.db.all("SELECT * FROM conversations")) == 1


def test_restore_rejects_zip_traversal_without_changing_target(tmp_path):
    """验证越界 ZIP 路径被拒绝，原数据目录保持完整。"""
    target = tmp_path / "data"
    target.mkdir()
    (target / "instance.json").write_text("unchanged")
    archive = tmp_path / "bad.zip"
    with ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", "bad")
    with pytest.raises(Problem, match="路径"):
        restore_backup(archive, target)
    assert (target / "instance.json").read_text() == "unchanged"
    assert not (tmp_path / "escape.txt").exists()


def test_running_instance_blocks_restore(tmp_path):
    """验证活动实例持有锁时不能恢复同一数据目录。"""
    target = tmp_path / "data"
    with instance_lock(target), pytest.raises(Problem, match="正在使用"):
        restore_backup(tmp_path / "unused.zip", target)


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 7])
def test_restore_rejects_unsupported_schema_without_changing_target(catalog, tmp_path, version):
    """恢复仅接受当前结构的备份，不匹配时保留目标数据并清理暂存目录。"""
    with catalog.db.transaction() as conn:
        conn.execute(f"PRAGMA user_version={version}")
    backup = create_backup(catalog.db, catalog.db.path.parent)
    target = tmp_path / "restored"
    target.mkdir()
    (target / "instance.json").write_text("unchanged")
    with pytest.raises(Problem, match="备份版本不受当前程序支持"):
        restore_backup(backup, target)
    assert (target / "instance.json").read_text() == "unchanged"
    assert not list(tmp_path.glob(".restored-restore-*"))
