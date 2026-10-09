"""同类排队不占工作线程，取消仍完成领域收尾"""

import threading

import pytest

from resume_maker.core.errors import Problem
from resume_maker.infrastructure import task_supervisor
from resume_maker.infrastructure.database import Database
from resume_maker.infrastructure.task_policy import TaskPolicy
from resume_maker.infrastructure.task_supervisor import TaskSupervisor


def test_serial_owner_does_not_starve_other_owner(tmp_path):
    """四项同类慢任务不能阻止另一个所有者立即开始执行"""
    supervisor = TaskSupervisor(Database(tmp_path / "resume.db"))
    supervisor.start()
    a, b = supervisor.scope("a", 1, {}), supervisor.scope("b", 1, {})
    release, entered, other = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def slow():
        """同类第一项占据执行资源，后继必须在池外等待"""
        calls.append("a")
        entered.set()
        assert release.wait(3)

    handles = [a.submit(str(i), threading.Event(), slow, {}) for i in range(4)]
    try:
        assert entered.wait(2)
        handle = b.submit("b", threading.Event(), other.set, {})
        assert other.wait(0.3)
        handle.join(2)
        assert calls == ["a"]
    finally:
        release.set()
        for handle in handles:
            handle.join(2)
        supervisor.stop(timeout=3)


def test_task_admission_is_bounded_and_duplicate_generic_key_is_idempotent(tmp_path):
    """队列满时拒绝新工作，已有幂等请求不占第二份容量"""
    supervisor = TaskSupervisor(
        Database(tmp_path / "resume.db"), policy=TaskPolicy(max_pending_tasks=1)
    )
    supervisor.start()
    entered, release = threading.Event(), threading.Event()
    calls = []

    def work(payload, cancelled):
        """维持一个已接收的通用任务"""
        calls.append(payload)
        entered.set()
        assert release.wait(3)

    supervisor.register("synthetic", "run", work)
    try:
        first = supervisor.submit("synthetic", "run", "one", generation=1, idempotency_key="one")
        assert entered.wait(2)
        assert (
            supervisor.submit("synthetic", "run", "one", generation=1, idempotency_key="one")["id"]
            == first["id"]
        )
        with pytest.raises(Problem, match="队列已满"):
            supervisor.submit("synthetic", "run", "two", generation=1, idempotency_key="two")
        assert calls == ["one"]
    finally:
        release.set()
        supervisor.stop(timeout=3)


def test_cancelled_waiting_owner_finishes_without_waiting_for_active_owner(tmp_path):
    """未开始的领域取消及时收尾，已经运行的任务仍保留真实租约"""
    supervisor = TaskSupervisor(Database(tmp_path / "resume.db"))
    supervisor.start()
    queue = supervisor.scope("a", 1, {})
    release, entered, cancelled = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def slow():
        """维持一个仍在实际回收资源的任务"""
        entered.set()
        assert release.wait(3)

    first = queue.submit("first", threading.Event(), slow, {})
    second = queue.submit(
        "second",
        cancelled,
        lambda: calls.append(False),
        {},
        on_cancel=lambda: calls.append(cancelled.is_set()),
    )
    try:
        assert entered.wait(2)
        cancelled.set()
        second.join(0.3)
        assert not second.is_alive()
        assert calls == [True]
        assert first.is_alive()
    finally:
        release.set()
        first.join(2)
        supervisor.stop(timeout=3)


def test_terminal_recovery_backs_off_continuous_failure_and_stops_after_success(
    tmp_path, monkeypatch
):
    """假时钟证明连续落盘失败不会每次取消轮询都重试，成功后停止补写"""
    supervisor = TaskSupervisor(Database(tmp_path / "resume.db"))
    clock, attempts = [0.0], []
    ready = threading.Event()
    monkeypatch.setattr(task_supervisor, "monotonic", lambda: clock[0])

    def finish():
        """只模拟本地终态持久化，不执行任务主体"""
        attempts.append(clock[0])
        if not ready.is_set():
            raise OSError("synthetic")

    supervisor.recover("synthetic", "one", finish)
    for index in range(2001):
        clock[0] = index * 0.05
        supervisor._retry_recoveries()
    assert attempts[:7] == [0.0, 0.5, 1.5, 3.5, 7.5, 15.5, 31.5]
    assert attempts[7:] == [61.5, 91.5]
    ready.set()
    clock[0] = 122
    supervisor._retry_recoveries()
    for _ in range(10):
        clock[0] += 30
        supervisor._retry_recoveries()
    assert len(attempts) == 10 and supervisor.recoveries == {}


def test_legacy_cancelled_domain_work_still_runs_its_cleanup(tmp_path):
    """未声明取消回调的旧队列继续进入领域函数完成原有收尾"""
    supervisor = TaskSupervisor(Database(tmp_path / "resume.db"))
    supervisor.start()
    cancelled = threading.Event()
    cancelled.set()
    calls = []
    try:
        handle = supervisor.scope("legacy", 1, {}).submit(
            "one", cancelled, lambda: calls.append(cancelled.is_set()), {}
        )
        handle.join(1)
        assert not handle.is_alive() and calls == [True]
    finally:
        supervisor.stop(timeout=3)
