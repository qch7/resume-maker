"""备份恢复保留资料、校验附件并隔离运行实例"""

import threading
from zipfile import ZipFile

import pytest

from resume_maker.core.errors import Problem
from resume_maker.infrastructure import storage
from resume_maker.infrastructure.assets import Assets
from resume_maker.infrastructure.database import SCHEMA_VERSION, Database
from resume_maker.infrastructure.storage import create_backup, instance_lock, restore_backup
from tests.support.data import make_catalog
from tests.support.templates import register_template


def test_restore_preserves_previous_data_and_drafts(catalog, project, populated, tmp_path):
    """验证备份恢复保留旧数据副本和已保存的输入草稿"""
    p, revision = project["id"], populated["id"]
    point = populated["content"]["highlights"][0]
    catalog.put_draft(p, revision, "highlight:one", {**point, "text": "pending text"}, 0)
    backup = create_backup(catalog.db, catalog.db.path.parent)
    target = tmp_path / "restored"
    target.mkdir()
    (target / "instance.json").write_text("old instance")
    previous = restore_backup(backup, target)
    assert (previous / "instance.json").read_text() == "old instance"
    restored = make_catalog(Database(target / "resume.db"))
    assert restored.working(p, revision)["content"]["highlights"][0]["text"] == "pending text"
    assert len(restored.db.all("SELECT * FROM conversations")) == 1


def test_restore_rejects_zip_traversal_without_changing_target(tmp_path):
    """验证越界 ZIP 路径被拒绝，原数据目录保持完整"""
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
    """验证活动实例持有锁时不能恢复同一数据目录"""
    target = tmp_path / "data"
    with instance_lock(target), pytest.raises(Problem, match="正在使用"):
        restore_backup(tmp_path / "unused.zip", target)


@pytest.mark.parametrize("name", ["data", "data.supervisor"])
def test_repository_lock_survives_data_directory_replacement(tmp_path, name):
    """源码实例和监督器锁集中在资料目录外，替换资料目录后仍拒绝第二个持有者"""
    project = tmp_path / "project"
    target = project / name
    target.mkdir(parents=True)
    (project / "pyproject.toml").write_text('[project]\nname = "resume-maker"\n')
    with instance_lock(target):
        target.rename(project / "previous")
        target.mkdir()
        with pytest.raises(Problem, match="正在使用"), instance_lock(target):
            pass
    assert not (project / f".{name}.instance.lock").exists()
    assert (project / ".local" / "locks" / f".{name}.instance.lock").is_file()


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 6, 7, 8, SCHEMA_VERSION + 1])
def test_restore_rejects_unsupported_schema_without_changing_target(catalog, tmp_path, version):
    """备份结构不匹配时保留目标数据并清理暂存目录"""
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


def test_backup_pins_concurrent_attachment_deletion(catalog, tmp_path, monkeypatch):
    """附件删除不等待压缩，固定副本确保恢复不会遇到悬空模板记录"""
    root = catalog.db.path.parent
    source = register_template(catalog, root)
    attempted, deleted = threading.Event(), threading.Event()

    def delete():
        """模拟业务删除事务，文件清理必须持有同一数据库写锁"""
        attempted.set()
        with catalog.db.transaction() as conn:
            conn.execute("DELETE FROM templates WHERE id='mapped'")
            source.unlink()
        deleted.set()

    worker = threading.Thread(target=delete)

    class ConcurrentZip(ZipFile):
        """在数据库快照完成后启动附件删除"""

        def __enter__(self):
            """删除已发起但不能在 ZIP 完成前拿到数据库写锁"""
            result = super().__enter__()
            worker.start()
            assert attempted.wait(2)
            assert deleted.wait(2)
            return result

    with monkeypatch.context() as patch:
        patch.setattr(storage, "ZipFile", ConcurrentZip)
        archive = create_backup(catalog.db, root)
    worker.join(3)
    assert deleted.is_set()
    restored = tmp_path / "restored"
    restore_backup(archive, restored)
    restored_assets = Assets(Database(restored / "resume.db"), restored)
    assert restored_assets.read_file("templates/mapped", "template.docx")


def test_corrupted_attachment_is_rejected_without_replacing_data(catalog, tmp_path):
    """ZIP 自身有效但附件正文被修改时，校验和阻止覆盖原数据"""
    register_template(catalog, catalog.db.path.parent)
    archive = create_backup(catalog.db, catalog.db.path.parent)
    corrupt = tmp_path / "corrupt.zip"
    with ZipFile(archive) as source, ZipFile(corrupt, "w") as target:
        for name in source.namelist():
            target.writestr(name, b"changed" if name.startswith("assets/") else source.read(name))
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "instance.json").write_text("preserved")
    with pytest.raises(Problem, match="校验失败"):
        restore_backup(corrupt, existing)
    assert (existing / "instance.json").read_text() == "preserved"


def test_nested_backup_metadata_name_remains_an_attachment(catalog, tmp_path):
    """附件中的同名文件照常校验，只有 ZIP 根目录清单不属于附件"""
    register_template(catalog, catalog.db.path.parent)
    staged = catalog.assets.stage_bundle(
        "ext.template-adapter", {"backup.json": b"synthetic attachment"}
    )
    with catalog.db.transaction() as conn:
        catalog.assets.update_bundle(conn, "ext.template-adapter", "templates/mapped", staged)
    archive = create_backup(catalog.db, catalog.db.path.parent)
    restored = tmp_path / "restored"
    restore_backup(archive, restored)
    restored_assets = Assets(Database(restored / "resume.db"), restored)
    assert restored_assets.read_file("templates/mapped", "backup.json") == b"synthetic attachment"
