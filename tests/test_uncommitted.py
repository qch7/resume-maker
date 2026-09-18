"""验证未提交工作副本的恢复、分支隔离和一次性提交语义"""

import pytest

from resume_maker.core.errors import Problem
from resume_maker.domain.models import ResumeItem
from resume_maker.infrastructure.database import Database
from resume_maker.services.catalog import Catalog
from resume_maker.services.projects import Projects


def test_edits_and_repeated_ordering_survive_restart_as_one_pending_change(
    catalog, project, populated
):
    """多次排序、文字修改和删除重启后仍为草稿；确认后只生成一个版本"""
    p, base = project["id"], populated["id"]
    one, two = populated["content"]["highlights"]
    resume = catalog.save_resume(
        "固定版本", None, [ResumeItem(project_id=p, revision_id=base, highlight_ids=["one", "two"])]
    )
    before = len(Projects(catalog).get_project(p)["revisions"])
    catalog.put_draft(p, base, "order", ["two", "one"], 0)
    catalog.put_draft(p, base, "order", ["one", "two"], 1)
    catalog.put_draft(p, base, "order", ["two", "one"], 2)
    catalog.put_draft(p, base, "highlight:one", {**one, "text": "Edited before commit"}, 0)
    catalog.put_draft(p, base, "highlight:new", {**two, "text": "Temporary addition"}, 0)
    catalog.put_draft(p, base, "highlight:new", None, 1)

    reopened = Catalog(Database(catalog.db.path))
    detail = Projects(reopened).get_project(p, base)
    assert len(detail["revisions"]) == before
    assert detail["branch"]["head_revision"] == base
    assert len(detail["uncommitted"]) == 1
    pending = detail["uncommitted"][0]
    assert pending["base_revision"] == base
    assert [h["id"] for h in pending["content"]["highlights"]] == ["two", "one"]
    assert pending["content"]["highlights"][1]["text"] == "Edited before commit"
    assert reopened.revision(base)["content"] == populated["content"]

    committed = reopened.save_revision(p, base, base)
    after = Projects(reopened).get_project(p, committed["id"])
    assert len(after["revisions"]) == before + 1
    assert committed["parent_id"] == base
    assert committed["content"] == pending["content"]
    assert after["uncommitted"] == []
    assert after["working"]["drafts"] == []
    assert (
        reopened.db.one("SELECT * FROM resumes WHERE id=?", (resume["id"],))["items"][0][
            "revision_id"
        ]
        == base
    )


def test_pending_changes_are_visible_across_branches_and_noop_orders_are_hidden(
    catalog, project, populated
):
    """历史树查询展示其他分支的草稿；恢复原顺序不会产生虚假改动节点"""
    p, base = project["id"], populated["id"]
    branch = catalog.history.create(p, base, "alternate", False)
    alternate = branch["head_revision"]
    catalog.put_draft(p, base, "order", ["two", "one"], 0)
    catalog.put_draft(p, alternate, "meta", {"title": "Alternate draft"}, 0)
    assert {d["base_revision"] for d in Projects(catalog).get_project(p, base)["uncommitted"]} == {
        base,
        alternate,
    }
    catalog.put_draft(p, base, "order", ["one", "two"], 1)
    detail = Projects(catalog).get_project(p, base)
    assert [d["base_revision"] for d in detail["uncommitted"]] == [alternate]
    assert catalog.save_revision(p, base, base)["id"] == base
    assert (
        Projects(catalog).get_project(p, alternate)["uncommitted"][0]["content"]["title"]
        == "Alternate draft"
    )


def test_failed_commit_keeps_working_tree_and_version_count(catalog, project, populated):
    """内容校验失败时草稿与历史均保留；修正后可以合并提交"""
    p, base = project["id"], populated["id"]
    catalog.put_draft(p, base, "highlight:new", {"title": "", "text": "", "evidence": []}, 0)
    before = Projects(catalog).get_project(p)
    with pytest.raises(Problem, match="草稿已保留"):
        catalog.save_revision(p, base, base)
    after = Projects(Catalog(Database(catalog.db.path))).get_project(p)
    assert after["revisions"] == before["revisions"]
    assert after["uncommitted"] == before["uncommitted"]
    assert after["working"] == before["working"]
