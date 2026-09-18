import pytest

from resume_maker.core.errors import Problem
from resume_maker.domain.experience import field_value
from resume_maker.domain.models import ResumeItem
from resume_maker.infrastructure.database import Database
from resume_maker.services.catalog import Catalog


def test_commit_publishes_all_drafts_and_preserves_pinned_resume(catalog, project, populated):
    """提交包含全部字段草稿；重启后保留新版本；已存简历仍引用原版本"""
    p, base = project["id"], populated["id"]
    resume = catalog.save_resume(
        "Application",
        None,
        [ResumeItem(project_id=p, revision_id=base, highlight_ids=["one", "two"])],
    )
    one, two = populated["content"]["highlights"]
    catalog.put_draft(p, base, "highlight:one", {**one, "text": "New parser"}, 0)
    catalog.put_draft(p, base, "highlight:two", {**two, "text": "New export"}, 0)
    saved = catalog.save_revision(p, base, base)
    assert saved["content"]["highlights"][0]["text"] == "New parser"
    assert saved["content"]["highlights"][1]["text"] == "New export"
    assert catalog.working(p, saved["id"])["content"]["highlights"][1]["text"] == "New export"
    assert catalog.revision(base)["content"]["highlights"][0]["text"] == "Parse documents"
    assert (
        catalog.db.one("SELECT * FROM resumes WHERE id=?", (resume["id"],))["items"][0][
            "revision_id"
        ]
        == base
    )
    reopened = Catalog(Database(catalog.db.path))
    assert reopened.working(p, saved["id"]) == {"content": saved["content"], "drafts": []}


def test_incomplete_draft_survives_but_cannot_publish(catalog, project, populated):
    """验证不完整内容可存草稿；但不能发布为正式经历"""
    p, base = project["id"], populated["id"]
    one = populated["content"]["highlights"][0]
    catalog.put_draft(p, base, "highlight:one", {**one, "text": ""}, 0)
    with pytest.raises(Problem, match="保存版本前"):
        catalog.save_revision(p, base, base)
    assert catalog.working(p, base)["content"]["highlights"][0]["text"] == ""


def test_stale_write_rejected(catalog, project, populated):
    """验证过期草稿版本不能覆盖其他窗口的修改"""
    p, base = project["id"], populated["id"]
    one = populated["content"]["highlights"][0]
    catalog.put_draft(p, base, "highlight:one", {**one, "text": "First writer"}, 0)
    with pytest.raises(Problem, match="其他窗口"):
        catalog.put_draft(p, base, "highlight:one", {**one, "text": "Late writer"}, 0)
    assert catalog.working(p, base)["content"]["highlights"][0]["text"] == "First writer"


def test_cross_project_revision_is_rejected(catalog, project, populated, tmp_path):
    """验证不能把其他项目的经历版本作为本项目内容"""
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
    """验证重复导入相同来源时复用项目并保留历史"""
    duplicate = catalog.create_project("New label", project["roots"])
    assert duplicate["id"] == project["id"]
    assert len(catalog.db.all("SELECT * FROM revisions")) == 1


def test_order_draft_survives_added_removed_highlights(catalog, project, populated):
    """验证新增亮点默认置顶；保存或删除后仍保留其他条目的手动排序"""
    p, revision = project["id"], populated["id"]
    catalog.put_draft(p, revision, "order", ["two", "one"], 0)
    point = {"id": "three", "title": "Extra", "text": "Pending extra", "evidence": []}
    catalog.put_draft(p, revision, "highlight:three", point, 0)
    assert field_value(catalog.working(p, revision)["content"], "order") == [
        "three",
        "two",
        "one",
    ]
    saved = catalog.save_revision(p, revision, revision)
    assert [h["id"] for h in saved["content"]["highlights"]] == ["three", "two", "one"]
    catalog.put_draft(p, saved["id"], "highlight:one", None, 0)
    assert [h["id"] for h in catalog.working(p, saved["id"])["content"]["highlights"]] == [
        "three",
        "two",
    ]
    published = catalog.save_revision(p, saved["id"], saved["id"])
    assert [h["id"] for h in published["content"]["highlights"]] == ["three", "two"]


def test_discard_rejects_stale_version(catalog, project, populated):
    """验证过期窗口不能删除后来更新的草稿"""
    p, revision = project["id"], populated["id"]
    point = populated["content"]["highlights"][0]
    catalog.put_draft(p, revision, "highlight:one", {**point, "text": "pending"}, 0)
    with pytest.raises(Problem, match="其他窗口"):
        catalog.discard_draft(p, revision, "highlight:one", 0)
    catalog.discard_draft(p, revision, "highlight:one", 1)
    assert catalog.working(p, revision)["content"] == populated["content"]


def test_restore_keeps_original_source_snapshot(catalog, project, populated):
    """验证恢复历史经历仍保留对应的原始来源快照"""
    from conftest import record_source_files

    snapshot = record_source_files(catalog.db, catalog.db.path.parent, project)
    with catalog.db.transaction() as conn:
        conn.execute(
            "UPDATE revisions SET snapshot_id=? WHERE id=?", (snapshot["id"], populated["id"])
        )
    restored = catalog.restore(project["id"], project["head_revision"], populated["id"])
    assert restored["snapshot_id"] is None
    again = catalog.restore(project["id"], populated["id"], restored["id"])
    assert again["snapshot_id"] == snapshot["id"]


@pytest.mark.parametrize("field", ["experience", "meta", "highlight:one", "order"])
def test_saving_unchanged_content_clears_drafts_without_a_new_revision(
    catalog, project, populated, field
):
    """验证内容未变时确认并清理草稿；无须制造重复版本"""
    p, base = project["id"], populated["id"]
    value = field_value(populated["content"], field)
    catalog.put_draft(p, base, field, value, 0)
    before = catalog.db.all("SELECT * FROM revisions")
    assert catalog.save_revision(p, base, base)["id"] == base
    assert catalog.working(p, base) == {"content": populated["content"], "drafts": []}
    assert catalog.db.all("SELECT * FROM revisions") == before


def test_save_all_clears_an_edit_reverted_to_saved_content(catalog, project, populated):
    """验证整段内容改回原值后可以清理全部无效草稿"""
    p, base = project["id"], populated["id"]
    point = populated["content"]["highlights"][0]
    catalog.put_draft(p, base, "highlight:one", {**point, "text": "Temporary edit"}, 0)
    catalog.put_draft(p, base, "highlight:one", point, 1)
    assert catalog.save_revision(p, base, base)["id"] == base
    assert not catalog.working(p, base)["drafts"]
    with pytest.raises(Problem, match="其他窗口"):
        catalog.put_draft(p, base, "highlight:one", {**point, "text": "Stale edit"}, 2)


def test_commit_includes_changes_alongside_unchanged_drafts(catalog, project, populated):
    """未变化字段不妨碍整段提交其他字段的最新草稿"""
    p, base = project["id"], populated["id"]
    one, two = populated["content"]["highlights"]
    catalog.put_draft(p, base, "highlight:one", one, 0)
    catalog.put_draft(p, base, "highlight:two", {**two, "text": "Pending change"}, 0)
    catalog.put_draft(p, base, "highlight:two", {**two, "text": "Still pending"}, 1)
    saved = catalog.save_revision(p, base, base)
    assert saved["id"] != base
    working = catalog.working(p, saved["id"])
    assert working["drafts"] == []
    assert working["content"]["highlights"][1]["text"] == "Still pending"


def test_commit_keeps_field_overrides_of_a_whole_experience_draft(catalog, project, populated):
    """整段提交保留单字段对整段草稿的有效覆盖"""
    from copy import deepcopy

    p, base = project["id"], populated["id"]
    content = deepcopy(populated["content"])
    content["title"] = "Pending title"
    content["highlights"][0]["text"] = "Whole draft text"
    catalog.put_draft(p, base, "experience", content, 0)
    catalog.put_draft(p, base, "highlight:one", populated["content"]["highlights"][0], 0)
    before = catalog.working(p, base)
    saved = catalog.save_revision(p, base, base)
    assert saved["content"] == before["content"]
    assert catalog.working(p, saved["id"])["drafts"] == []


def test_unchanged_save_rejects_stale_head(catalog, project, populated):
    """验证未改内容的保存操作仍须核验当前项目头版本"""
    p, base = project["id"], populated["id"]
    catalog.put_draft(p, base, "experience", populated["content"], 0)
    with pytest.raises(Problem, match="项目已有新版本"):
        catalog.save_revision(p, base, project["head_revision"])
    assert catalog.working(p, base)["drafts"]


def test_unchanged_save_rejects_concurrent_draft_edit(catalog, project, populated, monkeypatch):
    """验证保存确认期间的并发编辑会触发冲突而非丢失草稿"""
    p, base = project["id"], populated["id"]
    point = populated["content"]["highlights"][0]
    catalog.put_draft(p, base, "highlight:one", point, 0)
    working = catalog.working

    def concurrent_edit(project_id, revision_id):
        """在保存读取期间模拟另一窗口修改草稿；验证乐观锁拒绝覆盖"""
        result = working(project_id, revision_id)
        with catalog.db.transaction() as conn:
            conn.execute("UPDATE drafts SET version=version+1 WHERE project_id=?", (p,))
        return result

    monkeypatch.setattr(catalog, "working", concurrent_edit)
    with pytest.raises(Problem, match="保存时草稿发生变化"):
        catalog.save_revision(p, base, base)
    assert catalog.db.one("SELECT * FROM drafts WHERE project_id=?", (p,))["version"] == 2
