"""验证分支隔离、历史关系、AI 建议定位及旧数据库迁移。"""

import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_jobs import FakeProvider, wait_job

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.domain.models import ResumeItem
from resume_maker.infrastructure.database import (
    PROJECT_HIERARCHY,
    RESUME_DELETIONS,
    SCHEMA,
    Database,
    dump,
    uid,
)
from resume_maker.services.catalog import Catalog
from resume_maker.services.jobs import Jobs


def test_fork_drafts_save_restore_and_pinned_resume(catalog, project, populated):
    """同一节点分叉时草稿独立，保存和恢复只移动目标分支，简历引用不变。"""
    p, base = project["id"], populated["id"]
    one, two = populated["content"]["highlights"]
    catalog.put_draft(p, base, "highlight:one", {**one, "text": "Copied draft"}, 0)
    left = catalog.history.create(p, base, "后端岗位版", True)
    right = catalog.history.create(p, base, "AI 岗位版", False)
    assert left["head_revision"] != right["head_revision"]
    assert catalog.revision(left["head_revision"])["parent_id"] == base
    assert catalog.working(p, right["head_revision"])["drafts"] == []
    assert catalog.revision(left["head_revision"])["content"] == populated["content"]
    catalog.put_draft(p, left["head_revision"], "highlight:one", {**one, "text": "Left"}, 1)
    catalog.put_draft(p, left["head_revision"], "highlight:two", {**two, "text": "Pending"}, 0)
    saved = catalog.save_field(p, left["head_revision"], "highlight:one", left["head_revision"])
    assert saved["branch_id"] == left["id"]
    assert saved["parent_id"] == left["head_revision"]
    assert catalog.working(p, saved["id"])["content"]["highlights"][1]["text"] == "Pending"
    assert catalog.working(p, base)["content"]["highlights"][0]["text"] == "Copied draft"
    assert catalog.project(p)["head_revision"] == base
    resume = catalog.save_resume(
        "分支简历", None, [ResumeItem(project_id=p, revision_id=saved["id"], highlight_ids=["one"])]
    )
    main_saved = catalog.save_field(p, base, "experience", base)
    assert catalog.project(p)["head_revision"] == main_saved["id"]
    assert catalog.history.for_revision(p, saved["id"])["head_revision"] == saved["id"]
    with pytest.raises(Problem, match="未保存草稿"):
        catalog.restore(p, left["head_revision"], saved["id"])
    complete = catalog.save_field(p, saved["id"], "experience", saved["id"])
    restored = catalog.restore(p, left["head_revision"], complete["id"])
    assert restored["parent_id"] == complete["id"]
    assert restored["content"] == populated["content"]
    assert catalog.project(p)["head_revision"] == main_saved["id"]
    assert (
        catalog.db.one("SELECT * FROM resumes WHERE id=?", (resume["id"],))["items"][0][
            "revision_id"
        ]
        == saved["id"]
    )
    with pytest.raises(Problem, match="历史版本"):
        catalog.save_field(p, complete["id"], "experience", restored["id"])
    with pytest.raises(Problem, match="项目已有新版本"):
        catalog.save_field(p, restored["id"], "experience", complete["id"])
    reopened = Catalog(Database(catalog.db.path))
    assert reopened.history.branches(p) == catalog.history.branches(p)


def test_branch_api_validation_and_graph(tmp_path):
    """接口返回可绘制的父关系和分支指针，拒绝重名与跨项目创建。"""
    app = create_app(Config(data_dir=tmp_path / "data", token="test"))
    roots = [tmp_path / "one", tmp_path / "two"]
    for root in roots:
        root.mkdir()
    with TestClient(app, headers={"x-resume-token": "test"}) as client:
        parent, other = [
            client.post("/api/projects", json={"name": root.name, "roots": [str(root)]}).json()
            for root in roots
        ]
        url = f"/api/projects/{parent['id']}/branches"
        body = {"name": " Backend ", "base_revision": parent["head_revision"]}
        result = client.post(url, json=body)
        assert result.status_code == 200
        branch = result.json()
        assert branch["name"] == "Backend"
        assert client.post(url, json={**body, "name": "backend"}).status_code == 409
        assert client.post(url, json={**body, "name": "   "}).status_code == 400
        assert client.post(url, json={**body, "name": "bad\nname"}).status_code == 400
        assert (
            client.post(url, json={**body, "base_revision": other["head_revision"]}).status_code
            == 404
        )
        detail = client.get(
            f"/api/projects/{parent['id']}", params={"revision_id": branch["head_revision"]}
        ).json()
        assert detail["branch"] == branch
        assert len(detail["branches"]) == 2
        assert detail["revisions"][0]["parent_id"] == parent["head_revision"]
        assert detail["revisions"][0]["branch_id"] == branch["id"]
        assert client.get("/api/state").json()["branches"]


def test_ai_adoption_tracks_branch_head(catalog, project, tmp_path):
    """AI 建议只写入生成时的分支草稿，其他分支发布不使该建议过期。"""
    p, base = project["id"], project["head_revision"]
    branch = catalog.history.create(p, base, "AI 岗位版", False)
    provider = FakeProvider()
    jobs = Jobs(catalog.db, catalog, tmp_path / "data", provider)
    conv = catalog.create_conversation(p, "讨论岗位经历")
    jobs.start()
    try:
        job = jobs.submit(conv["id"], "分析分支", "analysis", branch["head_revision"], "all", uid())
        assert wait_job(catalog, job["id"])["status"] == "completed"
        assert provider.calls[0]["context"]["experience_branch"] == "AI 岗位版"
        catalog.put_draft(p, base, "meta", {"title": "Main changed"}, 0)
        catalog.save_field(p, base, "experience", base)
        proposal = catalog.db.one("SELECT * FROM proposals WHERE job_id=?", (job["id"],))
        catalog.adopt(proposal["id"])
        saved = catalog.save_field(
            p, branch["head_revision"], "experience", branch["head_revision"]
        )
        assert saved["content"]["description"] == "New analysis"
        assert saved["snapshot_id"] == proposal["snapshot_id"]
        second = jobs.submit(conv["id"], "再次分析", "analysis", saved["id"], "all", uid())
        assert wait_job(catalog, second["id"])["status"] == "completed"
        stale = catalog.db.one("SELECT * FROM proposals WHERE job_id=?", (second["id"],))
        catalog.put_draft(p, saved["id"], "meta", {"title": "Branch changed"}, 0)
        catalog.save_field(p, saved["id"], "experience", saved["id"])
        with pytest.raises(Problem, match="原文已发生变化"):
            catalog.adopt(stale["id"])
    finally:
        jobs.stop()


def test_v3_migration_preserves_history_and_drafts(tmp_path):
    """升级只补充分支关联，保留旧 ID、非线性父关系、草稿与简历引用。"""
    path = tmp_path / "old.db"
    content = {
        "title": "Legacy",
        "period": "",
        "role": "",
        "stack": [],
        "description": "",
        "highlights": [],
    }
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA + RESUME_DELETIONS + PROJECT_HIERARCHY + "PRAGMA user_version=3;")
        conn.execute("INSERT INTO projects VALUES ('p','Legacy','[]','{}','r3',0,'date','date')")
        for number, parent in [(1, None), (2, "r1"), (3, "r1")]:
            conn.execute(
                "INSERT INTO revisions VALUES (?, 'p', ?, NULL, ?, ?, 'manual', '', 'date')",
                (f"r{number}", parent, number, dump(content)),
            )
        conn.execute(
            "INSERT INTO drafts VALUES ('p','r3','meta',?,2,'manual','date')",
            (dump({"title": "Pending"}),),
        )
        conn.execute(
            "INSERT INTO resumes VALUES ('resume','Legacy',NULL,?,1,'date','date')",
            (dump([{"project_id": "p", "revision_id": "r2", "highlight_ids": []}]),),
        )
    catalog = Catalog(Database(path))
    branches = catalog.history.branches("p")
    assert len(branches) == 1 and branches[0]["name"] == "main"
    assert branches[0]["head_revision"] == "r3"
    assert catalog.revision("r3")["parent_id"] == "r1"
    assert catalog.revision("r2")["parent_id"] == "r1"
    assert catalog.working("p", "r3")["drafts"][0]["version"] == 2
    assert catalog.db.one("SELECT * FROM resumes")["items"][0]["revision_id"] == "r2"
    assert Catalog(Database(path)).history.branches("p") == branches
