"""任务真实结束、排队取消和重启恢复的可见保证"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import Database
from resume_maker.infrastructure.task_supervisor import TaskSupervisor


def test_cancelled_domain_task_retains_execution_lease_until_work_returns(tmp_path):
    """业务状态已取消也不能卸载正在执行的服务，只有函数退出才释放租约"""
    supervisor = TaskSupervisor(Database(tmp_path / "resume.db"))
    entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()

    def work():
        """模拟收到取消后仍需回收原生资源的执行器"""
        entered.set()
        assert release.wait(5)

    supervisor.start()
    queue = supervisor.scope("synthetic.tasks", 7, {"model": "fixed"})
    handle = queue.submit("entity", cancelled, work, {"handler": "render"})
    try:
        assert entered.wait(5)
        cancelled.set()
        assert supervisor.active({"synthetic.tasks"})[0]["state"] == "executing"
        with pytest.raises(Problem, match="租约"):
            supervisor.wait_owned("synthetic.tasks", timeout=0.01)
        assert handle.is_alive()
    finally:
        release.set()
        queue.close()
        supervisor.stop()
    assert not supervisor.active({"synthetic.tasks"})
    record = supervisor.db.all("SELECT value_json FROM settings WHERE key LIKE 'task-execution:%'")[
        0
    ]["value"]
    assert record["generation"] == 7 and record["providers"] == {"model": "fixed"}
    assert record["execution_state"] == "stopped" and record["cancellation_requested"]


def test_generic_queued_cancellation_does_not_call_handler(tmp_path):
    """排队时取消不能执行处理器，重启也不会自动重放该任务"""
    supervisor = TaskSupervisor(Database(tmp_path / "resume.db"))
    release, entered = threading.Event(), threading.Event()
    calls = []

    def occupy():
        """暂时占据唯一工作线程以固定排队取消时序"""
        entered.set()
        assert release.wait(5)

    supervisor.executor = ThreadPoolExecutor(max_workers=1)
    supervisor.executor.submit(occupy)
    assert entered.wait(5)
    supervisor.register("synthetic", "run", lambda payload, _cancel: calls.append(payload))
    task = supervisor.submit("synthetic", "run", {}, generation=1, idempotency_key="one")
    supervisor.cancel(task["id"])
    release.set()
    supervisor.stop()
    assert calls == []
    assert supervisor.db.setting(f"task:{task['id']}")["state"] == "cancelled"
    supervisor.start()
    supervisor.stop()
    assert calls == []


def test_execution_intent_rolls_back_with_business_transaction(tmp_path):
    """业务事务失败不能留下孤立执行意图或启动任务"""
    supervisor = TaskSupervisor(Database(tmp_path / "resume.db"))
    supervisor.start()
    queue = supervisor.scope("synthetic", 1, {})
    try:
        with pytest.raises(RuntimeError), supervisor.db.transaction() as conn:
            conn.execute("INSERT INTO settings VALUES ('synthetic', '{}')")
            queue.prepare(conn, "entity", {"handler": "work"})
            raise RuntimeError("rollback")
        assert supervisor.db.setting("synthetic") is None
        assert supervisor.db.all("SELECT key FROM settings WHERE key LIKE 'task-execution:%'") == []
    finally:
        supervisor.stop()


def test_executor_rejection_releases_lease_and_records_failure(tmp_path, monkeypatch):
    """线程池拒绝入队后保留诊断状态且允许插件关闭"""
    supervisor = TaskSupervisor(Database(tmp_path / "resume.db"))
    supervisor.start()
    queue = supervisor.scope("synthetic", 1, {})

    def reject(*args):
        """模拟已经关闭的执行器拒绝新工作"""
        raise RuntimeError("closed")

    monkeypatch.setattr(supervisor.executor, "submit", reject)
    try:
        with pytest.raises(RuntimeError):
            queue.submit("entity", threading.Event(), lambda: None, {})
        with pytest.raises(RuntimeError):
            supervisor.register("synthetic", "work", lambda *_: None)
            supervisor.submit("synthetic", "work", {}, generation=1, idempotency_key="one")
        assert not supervisor.active({"synthetic"})
        record = supervisor.db.all(
            "SELECT value_json FROM settings WHERE key LIKE 'task-execution:%'"
        )[0]["value"]
        assert record["execution_state"] == "schedule-failed"
    finally:
        supervisor.stop()


def test_terminal_write_failure_releases_actual_work_and_can_be_retried(tmp_path, monkeypatch):
    """磁盘失败不伪造在途执行，诊断和后续重试保留真实终态"""
    supervisor = TaskSupervisor(Database(tmp_path / "resume.db"))
    supervisor.start()
    original = supervisor.db.set_setting

    def fail_finished(key, value):
        """只让结束记录写入失败以固定资源回收时序"""
        if value.get("finished_at"):
            raise OSError("synthetic-private-body")
        original(key, value)

    monkeypatch.setattr(supervisor.db, "set_setting", fail_finished)
    queue = supervisor.scope("synthetic", 1, {})
    handle = queue.submit("entity", threading.Event(), lambda: None, {})
    handle.join(5)
    assert not handle.is_alive() and not supervisor.active({"synthetic"})
    assert supervisor.diagnostics()[0]["error_type"] == "OSError"
    assert "synthetic-private-body" not in str(supervisor.diagnostics())
    monkeypatch.setattr(supervisor.db, "set_setting", original)
    assert supervisor.retry_persistence() == []
    supervisor.stop()
