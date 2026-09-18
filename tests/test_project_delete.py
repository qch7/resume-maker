"""验证项目删除的引用保护、事务边界及项目组清理范围"""

from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient
from test_jobs import FakeProvider, wait_job
from test_subprojects import children, make_sources

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.domain.models import ResumeItem
from resume_maker.integrations.providers.base import Cancelled
from resume_maker.services.jobs import Jobs
from resume_maker.services.projects import Projects
from resume_maker.services.workspace import Workspace


def item(project):
    """使用项目固定版本构造简历引用；空亮点仍属于正在使用"""
    return ResumeItem(
        project_id=project["id"], revision_id=project["head_revision"], highlight_ids=[]
    )


def test_delete_project_api_refuses_used_project_until_removed_and_saved(tmp_path):
    """删除接口保护任意已保存简历；移除引用并保存后才允许删除且不改源码"""
    app = create_app(Config(data_dir=tmp_path / "data", token="test-token"))
    source = tmp_path / "source"
    source.mkdir()
    (source / "keep.txt").write_text("source stays", encoding="utf-8")
    headers = {"x-resume-token": "test-token"}
    with TestClient(app) as client:
        project = client.post(
            "/api/projects", headers=headers, json={"name": "待删除", "roots": [str(source)]}
        ).json()
        url = f"/api/projects/{project['id']}"
        resumes = [
            client.post(
                "/api/resumes",
                headers=headers,
                json={"name": name, "items": [item(project).model_dump()]},
            ).json()
            for name in ["研发岗位", "实习岗位"]
        ]
        assert client.delete(url).status_code == 401
        response = client.delete(url, headers=headers)
        assert response.status_code == 409
        assert "研发岗位" in response.text and "实习岗位" in response.text
        assert client.get(url, headers=headers).status_code == 200
        for resume in resumes:
            saved = client.put(
                f"/api/resumes/{resume['id']}",
                headers=headers,
                json={"name": resume["name"], "version": resume["version"], "items": []},
            )
            assert saved.status_code == 200
        response = client.delete(url, headers=headers)
        assert response.status_code == 200
        assert response.json() == {"deleted_project_ids": [project["id"]]}
        assert client.get(url, headers=headers).status_code == 404
        assert client.delete(url, headers=headers).status_code == 404
        state = client.get("/api/state", headers=headers).json()
        assert state["projects"] == state["conversations"] == state["branches"] == []
        assert len(state["resumes"]) == 2
        assert (source / "keep.txt").read_text(encoding="utf-8") == "source stays"


def test_group_deletion_is_blocked_by_child_reference(catalog, tmp_path):
    """任一子项目被引用时整组保留；已删除方案不再阻止项目删除"""
    parent = catalog.create_project("项目组", make_sources(tmp_path))
    subs = list(children(catalog, parent["id"]).values())
    resume = catalog.save_resume("子项目简历", None, [item(subs[0])])
    projects = Projects(catalog)
    with pytest.raises(Problem, match="子项目简历") as error:
        projects.delete(parent["id"])
    assert error.value.status == 409
    assert len(Workspace(catalog).state()["projects"]) == 3
    catalog.delete_resume(resume["id"], resume["version"])
    assert set(projects.delete(parent["id"])) == {parent["id"], *(p["id"] for p in subs)}
    assert Workspace(catalog).state()["projects"] == []
    assert all(Path(root).is_dir() for root in parent["roots"])


def test_delete_child_preserves_parent_sibling_and_their_resume(catalog, tmp_path):
    """单独删除子项目只移除该范围；父项目、同组兄弟及其简历保持原样"""
    parent = catalog.create_project("项目组", make_sources(tmp_path))
    first, second = children(catalog, parent["id"]).values()
    resume = catalog.save_resume("保留的简历", None, [item(parent), item(second)])
    assert Projects(catalog).delete(first["id"]) == [first["id"]]
    assert catalog.project(parent["id"])["roots"] == parent["roots"]
    assert catalog.project(second["id"])["parent_id"] == parent["id"]
    assert catalog.db.one("SELECT * FROM resumes WHERE id=?", (resume["id"],)) == resume


def test_delete_refuses_active_job_and_cleans_completed_history(catalog, project, tmp_path):
    """运行任务不能被删除；完成后经历、分支、草稿和会话依赖能在外键约束下清理"""
    conversation = catalog.db.one(
        "SELECT * FROM conversations WHERE project_id=?", (project["id"],)
    )
    jobs = Jobs(catalog.db, catalog, tmp_path / "data", FakeProvider())
    job = jobs.submit(
        conversation["id"], "分析项目", "analysis", project["head_revision"], "all", "one"
    )
    with pytest.raises(Problem, match="AI 任务"):
        Projects(catalog).delete(project["id"])
    jobs.start()
    try:
        assert wait_job(catalog, job["id"])["status"] == "completed"
    finally:
        jobs.stop()
    catalog.put_draft(project["id"], project["head_revision"], "meta", {"title": "新版本"}, 0)
    revision = catalog.save_revision(
        project["id"], project["head_revision"], project["head_revision"]
    )
    catalog.history.create(project["id"], revision["id"], "备选分支", False)
    catalog.put_draft(project["id"], revision["id"], "meta", {"title": "未提交"}, 0)
    Projects(catalog).delete(project["id"])
    with catalog.db.connect() as conn:
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        for table in [
            "projects",
            "revisions",
            "experience_branches",
            "revision_branches",
            "drafts",
            "snapshots",
            "conversations",
            "messages",
            "jobs",
            "events",
            "proposals",
        ]:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_concurrent_resume_save_cannot_reintroduce_deleted_project(catalog, project, monkeypatch):
    """模拟引用读取完成后被另一窗口删除；保存事务重新校验并拒绝悬空引用"""
    read_revision = catalog.revision

    def delete_after_read(*args, **kwargs):
        """在事务前的校验完成后交错执行项目删除"""
        revision = read_revision(*args, **kwargs)
        Projects(catalog).delete(project["id"])
        return revision

    monkeypatch.setattr(catalog, "revision", delete_after_read)
    with pytest.raises(Problem, match="项目已删除"):
        catalog.save_resume("并发简历", None, [item(project)])
    assert catalog.db.all("SELECT * FROM resumes") == []


def test_delete_cancelled_project_keeps_job_worker_alive(catalog, project, tmp_path):
    """取消后的进程可能迟到退出；删除其项目后仍能处理其他项目的 AI 任务"""
    started, release = Event(), Event()

    class DelayedProvider(FakeProvider):
        """固定首个任务退出时机以覆盖取消与项目删除交错"""

        def run(self, **kw):
            """首个任务等待项目被删除；后续任务正常响应"""
            if not started.is_set():
                started.set()
                if not release.wait(5):
                    raise RuntimeError("测试未释放任务")
                raise Cancelled("任务已取消")
            return super().run(**kw)

    jobs = Jobs(catalog.db, catalog, tmp_path / "data", DelayedProvider())
    conversation = catalog.db.one(
        "SELECT * FROM conversations WHERE project_id=?", (project["id"],)
    )
    jobs.start()
    try:
        job = jobs.submit(
            conversation["id"], "开始", "chat", project["head_revision"], "all", "cancel-one"
        )
        assert started.wait(5)
        with pytest.raises(Problem, match="AI 任务"):
            Projects(catalog).delete(project["id"])
        jobs.cancel(job["id"])
        Projects(catalog).delete(project["id"])
        release.set()
        other = catalog.create_project("新的项目", project["roots"])
        other_conversation = catalog.db.one(
            "SELECT * FROM conversations WHERE project_id=?", (other["id"],)
        )
        next_job = jobs.submit(
            other_conversation["id"], "继续", "chat", other["head_revision"], "all", "next-one"
        )
        assert wait_job(catalog, next_job["id"])["status"] == "completed"
        assert catalog.db.all("SELECT * FROM events WHERE job_id=?", (job["id"],)) == []
    finally:
        release.set()
        jobs.stop()
