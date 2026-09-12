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
