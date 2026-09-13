"""验证聚合项目的子项目登记、历史兼容、独立引用及 AI 上下文隔离。"""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_jobs import FakeProvider, wait_job

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.domain.models import Experience, ResumeItem
from resume_maker.infrastructure.database import RESUME_DELETIONS, SCHEMA, dump, now, uid
from resume_maker.services.jobs import Jobs
from resume_maker.services.projects import Projects
from resume_maker.services.workspace import Workspace


def make_sources(tmp_path):
    """创建含不同源码文件的两个独立子项目，避免读取真实源码。"""
    roots = [tmp_path / "agent", tmp_path / "rag"]
    for root in roots:
        root.mkdir()
        (root / f"{root.name}.py").write_text(f"NAME = '{root.name}'\n", encoding="utf-8")
    return [str(root.resolve()) for root in roots]


def children(catalog, parent_id):
    """通过工作台公开数据按来源定位子项目。"""
    return {
        p["roots"][0]: p
        for p in Workspace(catalog).state()["projects"]
        if p["parent_id"] == parent_id
    }


def test_import_exposes_independently_selectable_subprojects(tmp_path):
    """导入多来源项目后可分别引用整体或任一子项目，重复导入不会重复创建。"""
    app = create_app(Config(data_dir=tmp_path / "data", token="test-token"))
    roots = make_sources(tmp_path)
    headers = {"x-resume-token": "test-token"}
    with TestClient(app) as client:
        parent = client.post(
            "/api/projects", headers=headers, json={"name": "TrustGuard", "roots": roots}
        ).json()
        catalog = app.state.services.catalog
        subs = children(catalog, parent["id"])
        assert len(subs) == 2
        assert {p["name"] for p in subs.values()} == {"agent", "rag"}
        assert all(len(p["roots"]) == 1 for p in subs.values())
        again = client.post(
            "/api/projects", headers=headers, json={"name": "重复导入", "roots": roots[::-1]}
        ).json()
        assert again["id"] == parent["id"]
        assert len(catalog.db.all("SELECT * FROM projects")) == 3
        assert len(catalog.db.all("SELECT * FROM conversations")) == 3
        child = subs[roots[0]]
        item = {
            "project_id": child["id"],
            "revision_id": child["head_revision"],
            "highlight_ids": [],
        }
        resume = client.post(
            "/api/resumes", headers=headers, json={"name": "仅子项目", "items": [item]}
        ).json()
        assert resume["items"] == [item]
        assert parent["id"] not in [i["project_id"] for i in resume["items"]]
        detail = client.get(f"/api/projects/{child['id']}", headers=headers).json()
        assert detail["project"]["parent_id"] == parent["id"]
        assert detail["working"]["content"]["title"] == "agent"
        foreign = client.put(
            f"/api/projects/{child['id']}/draft",
            headers=headers,
            json={
                "base_revision": parent["head_revision"],
                "field": "meta",
                "value": {"title": "错误版本"},
            },
        )
        assert foreign.status_code == 409


def test_source_changes_keep_subproject_identity_and_existing_history(catalog, tmp_path):
    """复用已有单项目，来源重排保留子项目 ID，移除来源仅解除分组。"""
    roots = make_sources(tmp_path)
    standalone = catalog.create_project("已有 agent", [roots[0]])
    conversation = catalog.db.one(
        "SELECT * FROM conversations WHERE project_id=?", (standalone["id"],)
    )
    parent = catalog.create_project("TrustGuard", roots)
    before = children(catalog, parent["id"])
    assert before[roots[0]]["id"] == standalone["id"]
    projects = Projects(catalog)
    projects.update_sources(parent["id"], "TrustGuard", roots[::-1])
    assert {root: p["id"] for root, p in children(catalog, parent["id"]).items()} == {
        root: p["id"] for root, p in before.items()
    }
    rebound = tmp_path / "agent-moved"
    rebound.mkdir()
    projects.update_sources(standalone["id"], "agent", [str(rebound)])
    assert catalog.project(standalone["id"])["parent_id"] == parent["id"]
    assert str(rebound.resolve()) in catalog.project(parent["id"])["roots"]
    assert catalog.conversation(conversation["id"])["project_id"] == standalone["id"]
    with pytest.raises(Problem, match="同组"):
        projects.update_sources(standalone["id"], "agent", [roots[1]])
    with pytest.raises(Problem, match="只能关联一个"):
        projects.update_sources(standalone["id"], "agent", roots)
    projects.update_sources(parent["id"], "TrustGuard", [roots[1]])
    assert children(catalog, parent["id"]) == {}
    assert catalog.project(standalone["id"])["parent_id"] is None
    assert catalog.revision(standalone["head_revision"])["project_id"] == standalone["id"]
    assert catalog.conversation(conversation["id"]) == conversation


def test_parent_and_subproject_jobs_use_separate_sources_histories_and_threads(catalog, tmp_path):
    """整体读取全部来源，子项目仅读取自身来源，三者不共享模型会话和消息。"""
    roots = make_sources(tmp_path)
    parent = catalog.create_project("TrustGuard", roots)
    subs = children(catalog, parent["id"])
    provider = FakeProvider()
    jobs = Jobs(catalog.db, catalog, tmp_path / "data", provider)
    projects = [parent, subs[roots[0]], subs[roots[1]]]
    conversations = [
        catalog.db.one("SELECT * FROM conversations WHERE project_id=?", (p["id"],))
        for p in projects
    ]
    jobs.start()
    try:
        for project, conversation in zip(projects, conversations, strict=True):
            job = jobs.submit(
                conversation["id"],
                f"仅此范围消息 {project['name']}",
                "analysis",
                project["head_revision"],
                "all",
                uid(),
            )
            assert wait_job(catalog, job["id"])["status"] == "completed"
            context = provider.calls[-1]["context"]
            manifest = json.loads(
                (Path(context["snapshot_directory"]) / "manifest.json").read_text(encoding="utf-8")
            )
            assert {source["path"] for source in manifest["sources"]} == set(project["roots"])
            expected_files = (
                {"agent.py", "rag.py"}
                if project["id"] == parent["id"]
                else {f"{project['name']}.py"}
            )
            assert {file["path"] for file in manifest["files"]} == expected_files
            assert context["current_experience"]["title"] == project["name"]
            assert context["recent_messages"] == [
                {"role": "user", "text": f"仅此范围消息 {project['name']}"}
            ]
        threads = [catalog.conversation(c["id"])["provider_thread_id"] for c in conversations]
        assert len(set(threads)) == 3
        followup = jobs.submit(
            conversations[1]["id"],
            "agent 后续讨论",
            "chat",
            projects[1]["head_revision"],
            "all",
            uid(),
        )
        assert wait_job(catalog, followup["id"])["status"] == "completed"
        context = provider.calls[-1]["context"]
        assert provider.calls[-1]["thread"] == threads[1]
        assert context["parent_project"] == "TrustGuard"
        assert "仅此范围消息 agent" in dump(context["recent_messages"])
        assert "仅此范围消息 rag" not in dump(context["recent_messages"])
        assert "仅此范围消息 TrustGuard" not in dump(context["recent_messages"])
    finally:
        jobs.stop()
    child = projects[1]
    catalog.put_draft(
        child["id"],
        child["head_revision"],
        "highlight:child-only",
        {"title": "独立亮点", "text": "子项目实现", "evidence": []},
        0,
    )
    published = catalog.save_field(
        child["id"], child["head_revision"], "highlight:child-only", child["head_revision"]
    )
    assert catalog.working(parent["id"], parent["head_revision"])["content"]["highlights"] == []
    assert catalog.working(projects[2]["id"], projects[2]["head_revision"])["drafts"] == []
    resume = catalog.save_resume(
        "仅子项目",
        None,
        [
            ResumeItem(
                project_id=child["id"], revision_id=published["id"], highlight_ids=["child-only"]
            )
        ],
    )
    assert len(resume["items"]) == 1


def test_upgrade_keeps_whole_project_history_even_if_sources_are_missing(tmp_path):
    """旧聚合项目自动补齐子项目，离线目录不会阻止升级，也不会重建原会话。"""
    data = tmp_path / "data"
    data.mkdir()
    roots = [str(tmp_path / "missing-agent"), str(tmp_path / "missing-rag")]
    with sqlite3.connect(data / "resume.db") as conn:
        conn.executescript(SCHEMA + RESUME_DELETIONS + "PRAGMA user_version=2;")
        conn.execute(
            "INSERT INTO projects VALUES (?,?,?,?,?,0,?,?)",
            ("parent", "TrustGuard", dump(roots), "{}", "revision", now(), now()),
        )
        conn.execute(
            "INSERT INTO revisions VALUES (?,?,NULL,NULL,1,?,?,?,?)",
            (
                "revision",
                "parent",
                dump(Experience(title="原整体经历", description="保留的经历").model_dump()),
                "manual",
                "原经历",
                now(),
            ),
        )
        conn.execute(
            "INSERT INTO conversations(id,project_id,title,provider_thread_id,input_draft,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            ("conversation", "parent", "原整体对话", "model-thread", "未发送草稿", now(), now()),
        )
    config = Config(data_dir=data)
    catalog = create_app(config).state.services.catalog
    assert catalog.project("parent")["head_revision"] == "revision"
    assert catalog.revision("revision")["content"]["description"] == "保留的经历"
    assert catalog.conversation("conversation")["provider_thread_id"] == "model-thread"
    assert catalog.conversation("conversation")["input_draft"] == "未发送草稿"
    assert len(children(catalog, "parent")) == 2
    reopened = create_app(config).state.services.catalog
    assert len(reopened.db.all("SELECT * FROM projects")) == 3
    assert len(reopened.db.all("SELECT * FROM conversations")) == 3
