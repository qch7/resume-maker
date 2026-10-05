"""后台经历任务的可控模型和完成等待"""

import json
import time

import pytest

from resume_maker.domain.models import AIResult, Experience
from resume_maker.infrastructure.database import uid
from resume_maker.sdk.model import Cancelled
from tests.support.providers import ProviderStub


class FakeProvider(ProviderStub):
    """可控 AI 替身以免自动测试调用真实 CLI 或消耗模型额度"""

    def __init__(self, block=False):
        """配置测试替身是否等待取消，用于覆盖成功和取消两条任务路径"""
        self.calls, self.block = [], block

    def run(self, **kw):
        """返回可预测的结构化建议并模拟独立会话标识和取消信号"""
        context = json.loads(kw["prompt"].split("本轮上下文数据：\n")[1])
        self.calls.append(
            {
                "context": context,
                "thread": kw["thread_id"],
                "settings": kw["settings"],
                "sources": kw.get("sources", []),
            }
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
    """为慢速 CI 留出数据库等待余量，超时报告任务状态和最后事件"""
    until = time.monotonic() + 30
    while True:
        job = catalog.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if job["status"] not in {"queued", "running"}:
            return job
        if time.monotonic() >= until:
            event = catalog.db.one(
                "SELECT kind,data_json FROM events WHERE job_id=? ORDER BY id DESC LIMIT 1",
                (job_id,),
            )
            pytest.fail(
                f"job {job_id} did not finish: status={job['status']}, "
                f"error={job['error']}, last_event={event}"
            )
        time.sleep(0.05)
