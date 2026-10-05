"""test_jobs.py：可控 AI 替身以免自动测试调用真实 CLI 或消耗模型额度"""

import json
import time

import pytest

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import uid
from resume_maker.integrations.source_service import SourceService
from resume_maker.services.conversations import Conversations
from resume_maker.services.jobs import Jobs
from tests.support.jobs import FakeProvider, wait_job


def test_independent_sessions_and_stale_proposal(catalog, project, tmp_path):
    """验证不同会话上下文隔离并拒绝采用基于过期原文的建议"""
    provider = FakeProvider()
    jobs = Jobs(
        catalog.db,
        catalog,
        tmp_path / "data",
        provider,
        source_service=SourceService(catalog, tmp_path / "data", assets=catalog.assets),
    )
    first = catalog.db.all("SELECT * FROM conversations")[0]
    second = Conversations(catalog, storage=catalog.db).create_conversation(project["id"], "Second")
    jobs.start()
    try:
        one = jobs.submit(
            first["id"], "分析项目", "analysis", project["head_revision"], "all", uid()
        )
        assert wait_job(catalog, one["id"])["status"] == "completed"
        initial_thread = Conversations(catalog, storage=catalog.db).conversation(first["id"])[
            "provider_thread_id"
        ]
        two = jobs.submit(
            second["id"], "另一条会话", "chat", project["head_revision"], "all", uid()
        )
        assert wait_job(catalog, two["id"])["status"] == "completed"
        assert (
            Conversations(catalog, storage=catalog.db).conversation(second["id"])[
                "provider_thread_id"
            ]
            != initial_thread
        )
        three = jobs.submit(first["id"], "继续", "chat", project["head_revision"], "all", uid())
        assert wait_job(catalog, three["id"])["status"] == "completed"
        assert provider.calls[-1]["thread"] == initial_thread
        assert "另一条会话" not in json.dumps(provider.calls[-1]["context"], ensure_ascii=False)
        proposal = catalog.db.all("SELECT * FROM proposals")[0]
        base = project["head_revision"]
        catalog.put_draft(project["id"], base, "meta", {"title": "User changed title"}, 0)
        with pytest.raises(Problem, match="原文已发生变化"):
            Conversations(catalog, storage=catalog.db).adopt(proposal["id"])
    finally:
        jobs.stop()


def test_cancel_does_not_publish_reply(catalog, project, tmp_path):
    """验证任务取消后不会发布迟到的模型回复或建议"""
    jobs = Jobs(
        catalog.db,
        catalog,
        tmp_path / "data",
        FakeProvider(block=True),
        source_service=SourceService(catalog, tmp_path / "data", assets=catalog.assets),
    )
    conv = catalog.db.all("SELECT * FROM conversations")[0]
    jobs.start()
    try:
        job = jobs.submit(
            conv["id"], "analysis", "analysis", project["head_revision"], "all", uid()
        )
        until = time.monotonic() + 3
        while not jobs.provider.calls and time.monotonic() < until:
            time.sleep(0.01)
        jobs.cancel(job["id"])
        assert wait_job(catalog, job["id"])["status"] == "cancelled"
    finally:
        jobs.stop()
    assert not catalog.db.all("SELECT * FROM messages WHERE role='assistant'")
    assert not catalog.db.all("SELECT * FROM proposals")
