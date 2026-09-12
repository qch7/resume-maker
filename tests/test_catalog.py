import pytest

from resume_maker.catalog import Catalog, Problem
from resume_maker.db import Database
from resume_maker.models import ResumeItem


def test_single_field_save_preserves_other_drafts_and_old_resume(catalog, project, populated):
    p, base = project["id"], populated["id"]
    resume = catalog.save_resume(
        "Application",
        None,
        [ResumeItem(project_id=p, revision_id=base, highlight_ids=["one", "two"])],
    )
    one, two = populated["content"]["highlights"]
    catalog.put_draft(p, base, "highlight:one", {**one, "text": "New parser"}, 0)
    catalog.put_draft(p, base, "highlight:two", {**two, "text": "New export"}, 0)
    saved = catalog.save_field(p, base, "highlight:one", base)
    assert saved["content"]["highlights"][0]["text"] == "New parser"
    assert saved["content"]["highlights"][1]["text"] == "Export Word"
    assert catalog.working(p, saved["id"])["content"]["highlights"][1]["text"] == "New export"
    assert catalog.revision(base)["content"]["highlights"][0]["text"] == "Parse documents"
    assert (
        catalog.db.one("SELECT * FROM resumes WHERE id=?", (resume["id"],))["items"][0][
            "revision_id"
        ]
        == base
    )
    reopened = Catalog(Database(catalog.db.path))
    assert reopened.working(p, saved["id"])["drafts"]


def test_incomplete_draft_survives_but_cannot_publish(catalog, project, populated):
    p, base = project["id"], populated["id"]
    one = populated["content"]["highlights"][0]
    catalog.put_draft(p, base, "highlight:one", {**one, "text": ""}, 0)
    with pytest.raises(Problem, match="保存版本前"):
        catalog.save_field(p, base, "highlight:one", base)
    assert catalog.working(p, base)["content"]["highlights"][0]["text"] == ""


def test_stale_write_rejected(catalog, project, populated):
    p, base = project["id"], populated["id"]
    one = populated["content"]["highlights"][0]
    catalog.put_draft(p, base, "highlight:one", {**one, "text": "First writer"}, 0)
    with pytest.raises(Problem, match="其他窗口"):
        catalog.put_draft(p, base, "highlight:one", {**one, "text": "Late writer"}, 0)
    assert catalog.working(p, base)["content"]["highlights"][0]["text"] == "First writer"


def test_cross_project_revision_is_rejected(catalog, project, populated, tmp_path):
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = catalog.create_project("Other", [str(other_dir)])
    with pytest.raises(Problem, match="不属于"):
        catalog.save_resume(
            "Invalid",
            None,
            [ResumeItem(project_id=other["id"], revision_id=populated["id"], highlight_ids=[])],
        )


def test_duplicate_registration_keeps_history(catalog, project):
    duplicate = catalog.create_project("New label", project["roots"])
    assert duplicate["id"] == project["id"]
    assert len(catalog.db.all("SELECT * FROM revisions")) == 1


def test_order_draft_survives_added_removed_highlights(catalog, project, populated):
    p, revision = project["id"], populated["id"]
    catalog.put_draft(p, revision, "order", ["two", "one"], 0)
    point = {"id": "three", "title": "Extra", "text": "Pending extra", "evidence": []}
    catalog.put_draft(p, revision, "highlight:three", point, 0)
    saved = catalog.save_field(p, revision, "order", revision)
    assert [h["id"] for h in saved["content"]["highlights"]] == ["two", "one"]
    catalog.put_draft(p, saved["id"], "highlight:one", None, 0)
    assert [h["id"] for h in catalog.working(p, saved["id"])["content"]["highlights"]] == [
        "two",
        "three",
    ]


def test_discard_rejects_stale_version(catalog, project, populated):
    p, revision = project["id"], populated["id"]
    point = populated["content"]["highlights"][0]
    catalog.put_draft(p, revision, "highlight:one", {**point, "text": "pending"}, 0)
    with pytest.raises(Problem, match="其他窗口"):
        catalog.discard_draft(p, revision, "highlight:one", 0)
    catalog.discard_draft(p, revision, "highlight:one", 1)
    assert catalog.working(p, revision)["content"] == populated["content"]


def test_restore_keeps_original_source_snapshot(catalog, project, populated):
    from resume_maker.sources import collect_snapshot

    snapshot = collect_snapshot(catalog.db, catalog.db.path.parent, project)
    with catalog.db.transaction() as conn:
        conn.execute(
            "UPDATE revisions SET snapshot_id=? WHERE id=?", (snapshot["id"], populated["id"])
        )
    restored = catalog.restore(project["id"], project["head_revision"], populated["id"])
    assert restored["snapshot_id"] is None
    again = catalog.restore(project["id"], populated["id"], restored["id"])
    assert again["snapshot_id"] == snapshot["id"]
