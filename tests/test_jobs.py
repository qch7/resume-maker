"""test_jobs.py：可控 AI 替身以免自动测试调用真实 CLI 或消耗模型额度"""

import json
import time

import pytest

from resume_maker.core.errors import Problem
from resume_maker.domain.models import AIResult, Experience
from resume_maker.infrastructure.database import uid
from resume_maker.integrations.providers.base import Cancelled
from resume_maker.services.jobs import Jobs


class FakeProvider:
    """可控 AI 替身以免自动测试调用真实 CLI 或消耗模型额度"""

    def __init__(self, block=False):
        """配置测试替身是否等待取消；用于覆盖成功与取消两条任务路径"""
        self.calls, self.block = [], block

    def run(self, **kw):
        """返回可预测的结构化建议并模拟独立会话标识与取消信号"""
        context = json.loads(kw["prompt"].split("本轮上下文数据：\n")[1])
        self.calls.append(
            {"context": context, "thread": kw["thread_id"], "settings": kw["settings"]}
        )
        kw["emit"]("thread", {"id": kw["thread_id"] or uid()})
        while self.block:
            if kw["cancelled"].wait(0.01):
                raise Cancelled("cancelled")
        if context["task"] == "analysis":
            value = {**context["current_experience"], "description": "New analysis"}
            return AIResult(
                reply="草稿已准备，请核对",
                experience=Experience.model_validate(value),
                changes=[],
                questions=[],
            )
        return AIResult(reply="收到本项目的新消息", experience=None, changes=[], questions=[])


def wait_job(catalog, job_id):
    """在有界时间内等待后台任务结束；超时则报告测试失败"""
    until = time.monotonic() + 5
    while time.monotonic() < until:
        job = catalog.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(0.02)
    pytest.fail("job did not finish")


def test_independent_sessions_and_stale_proposal(catalog, project, tmp_path):
    """验证不同会话上下文隔离并拒绝采用基于过期原文的建议"""
    provider = FakeProvider()
    jobs = Jobs(catalog.db, catalog, tmp_path / "data", provider)
    first = catalog.db.all("SELECT * FROM conversations")[0]
    second = catalog.create_conversation(project["id"], "Second")
    jobs.start()
    try:
        one = jobs.submit(
            first["id"], "分析项目", "analysis", project["head_revision"], "all", uid()
        )
        assert wait_job(catalog, one["id"])["status"] == "completed"
        initial_thread = catalog.conversation(first["id"])["provider_thread_id"]
        two = jobs.submit(
            second["id"], "另一条会话", "chat", project["head_revision"], "all", uid()
        )
        assert wait_job(catalog, two["id"])["status"] == "completed"
        assert catalog.conversation(second["id"])["provider_thread_id"] != initial_thread
        three = jobs.submit(first["id"], "继续", "chat", project["head_revision"], "all", uid())
        assert wait_job(catalog, three["id"])["status"] == "completed"
        assert provider.calls[-1]["thread"] == initial_thread
        assert "另一条会话" not in json.dumps(provider.calls[-1]["context"], ensure_ascii=False)
        proposal = catalog.db.all("SELECT * FROM proposals")[0]
        base = project["head_revision"]
        catalog.put_draft(project["id"], base, "meta", {"title": "User changed title"}, 0)
        with pytest.raises(Problem, match="原文已发生变化"):
            catalog.adopt(proposal["id"])
    finally:
        jobs.stop()


def test_cancel_does_not_publish_reply(catalog, project, tmp_path):
    """验证任务取消后不会发布迟到的模型回复或建议"""
    jobs = Jobs(catalog.db, catalog, tmp_path / "data", FakeProvider(block=True))
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
