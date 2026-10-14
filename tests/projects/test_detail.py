"""项目详情按同一快照批量读取草稿，仅按需返回历史正文"""

from contextlib import contextmanager

import pytest

from resume_maker.core.errors import Problem
from resume_maker.plugin_packages.sys_experience.services.projects import Projects


@pytest.mark.parametrize("count", [0, 1, 12])
def test_detail_batches_drafts_without_loading_all_revision_bodies(
    catalog, project, populated, monkeypatch, count
):
    """分支数增加不增加查询次数，完整关系及每份草稿仍准确对应不可变基线"""
    identifier, base = project["id"], populated["id"]
    expected = {}
    for index in range(count):
        branch = catalog.history.create(identifier, base, f"岗位 {index}", False)
        revision = branch["head_revision"]
        catalog.put_draft(identifier, revision, "meta", {"title": f"草稿 {index}"}, 0)
        catalog.put_draft(identifier, revision, "order", ["two", "one"], 0)
        expected[revision] = catalog.working(identifier, revision)
    queries, connections = [], []
    original = catalog.db.connect

    @contextmanager
    def connect():
        """记录本次详情读取的连接及实际 SQL，不依赖计时阈值"""
        with original() as conn:
            connections.append(conn)
            conn.set_trace_callback(queries.append)
            yield conn

    monkeypatch.setattr(catalog.db, "connect", connect)
    selected = next(iter(expected), base)
    detail = Projects(catalog).get_project(identifier, selected)
    assert len(connections) == 1
    assert queries[0] == "BEGIN"
    assert sum(query.startswith("SELECT ") for query in queries) == 8
    assert detail["revision"]["id"] == selected
    assert detail["revision"]["content"] == populated["content"]
    assert detail["working"] == expected.get(
        selected, {"content": populated["content"], "drafts": []}
    )
    assert len(detail["revisions"]) == count + 2
    assert all("content" not in row for row in detail["revisions"])
    assert [row["number"] for row in detail["revisions"]] == list(range(count + 2, 0, -1))
    assert {row["base_revision"]: row["content"] for row in detail["uncommitted"]} == {
        revision: value["content"] for revision, value in expected.items()
    }
    assert all(row["parent_id"] == base for row in detail["revisions"][:count])


def test_detail_does_not_mix_concurrent_branch_commits(catalog, project, monkeypatch):
    """第一次读取后另一个连接新增分支，当前详情仍只包含原快照"""
    original = catalog.project
    created = []

    def project_then_fork(identifier, conn=None):
        """在项目查询完成后提交另一分支，模拟窗口并发操作"""
        value = original(identifier, conn)
        created.append(catalog.history.create(identifier, value["head_revision"], "新岗位", False))
        return value

    monkeypatch.setattr(catalog, "project", project_then_fork)
    detail = Projects(catalog).get_project(project["id"])
    assert len(detail["branches"]) == len(detail["revisions"]) == 1
    assert detail["revision"]["id"] == project["head_revision"]
    assert created[0]["id"] not in {branch["id"] for branch in detail["branches"]}
    monkeypatch.setattr(catalog, "project", original)
    assert len(Projects(catalog).get_project(project["id"])["revisions"]) == 2


def test_detail_rejects_revision_from_another_project(catalog, project):
    """按需正文读取继续校验项目归属，不能用其他项目的版本构造工作副本"""
    other = catalog.create_project("其他项目", [])
    with pytest.raises(Problem, match="不属于该项目"):
        Projects(catalog).get_project(project["id"], other["head_revision"])
