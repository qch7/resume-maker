from zipfile import ZipFile

import pytest

from resume_maker.catalog import Catalog, Problem
from resume_maker.db import Database
from resume_maker.storage import create_backup, instance_lock, restore_backup


def test_restore_preserves_previous_data_and_drafts(catalog, project, populated, tmp_path):
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
    target = tmp_path / "data"
    with instance_lock(target), pytest.raises(Problem, match="正在使用"):
        restore_backup(tmp_path / "unused.zip", target)
