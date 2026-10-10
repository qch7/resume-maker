"""所有模型入口共用实际调用容量，任务副本不会复制容量池"""

import threading
from types import SimpleNamespace

import pytest

from resume_maker.domain.models import ProviderSettings
from resume_maker.integrations import privacy_gateway
from resume_maker.integrations.privacy_gateway import ModelCapacity, PrivacyGateway
from resume_maker.sdk.model import Cancelled, ProviderError


def test_five_model_calls_do_not_exceed_shared_capacity(tmp_path):
    """模拟慢供应商，四个真实调用已开始时第五个仍须等待"""
    lock, release, four, five = (
        threading.Lock(),
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    calls, active, peak, errors = [], 0, 0, []

    def runner(*args, **kwargs):
        """只返回合成结果，计数实际传输入口并控制结束时机"""
        nonlocal active, peak
        with lock:
            calls.append(1)
            active += 1
            peak = max(peak, active)
            if len(calls) == 4:
                four.set()
            if len(calls) == 5:
                five.set()
        try:
            assert release.wait(3)
            return '{"reply":"ok","experience":null,"changes":[],"questions":[]}'
        finally:
            with lock:
                active -= 1

    gateway = PrivacyGateway(runner=runner)

    def call():
        """连接检查和独立任务均使用同一个隐私出口"""
        try:
            gateway.with_private_data({}).run(
                workspace=tmp_path,
                prompt="synthetic",
                thread_id=None,
                settings=ProviderSettings(),
                cancelled=threading.Event(),
                emit=lambda *_: None,
            )
        except Exception as exc:
            errors.append(type(exc).__name__)

    workers = [threading.Thread(target=call) for _ in range(5)]
    try:
        for worker in workers:
            worker.start()
        assert four.wait(2)
        assert not five.wait(0.3)
        assert peak == 4
    finally:
        release.set()
        for worker in workers:
            worker.join(2)
    assert not errors and len(calls) == 5 and peak == 4


def test_waiting_cancellation_failure_and_instances_release_capacity():
    """排队取消不调用传输，连续失败归还容量，独立实例没有共同锁"""
    capacity = ModelCapacity(parallel=1, waiting=1, wait_seconds=0.02)
    other = ModelCapacity(parallel=1)
    cancelled = threading.Event()
    cancelled.set()
    with capacity.enter(threading.Event()):
        with pytest.raises(Cancelled), capacity.enter(cancelled):
            pytest.fail("取消任务不能进入模型传输")
        with pytest.raises(ProviderError, match="预算"), capacity.enter(threading.Event()):
            pytest.fail("超时任务不能进入模型传输")
        with other.enter(threading.Event()):
            assert other.active == 1
    for _ in range(3):
        with pytest.raises(ProviderError), capacity.enter(threading.Event()):
            raise ProviderError("synthetic")
        assert capacity.active == 0 and capacity.pending == 0


def test_full_wait_queue_and_mid_wait_cancellation_never_start_transport():
    """等待容量满时拒绝第三项，正在等待的取消不会触发额外模型调用"""
    capacity = ModelCapacity(parallel=1, waiting=1, wait_seconds=2)
    cancelled, starting = threading.Event(), threading.Event()
    calls, failures = [], []

    def wait():
        """模拟第二个调用等待同一出口"""
        starting.set()
        try:
            with capacity.enter(cancelled):
                calls.append(2)
        except Exception as exc:
            failures.append(type(exc))

    worker = threading.Thread(target=wait)
    try:
        with capacity.enter(threading.Event()):
            calls.append(1)
            worker.start()
            assert starting.wait(1)
            with capacity.condition:
                assert capacity.condition.wait_for(lambda: capacity.pending == 1, 0.2)
            with pytest.raises(ProviderError, match="队列已满"), capacity.enter(threading.Event()):
                calls.append(3)
            cancelled.set()
            worker.join(0.5)
            assert not worker.is_alive() and failures == [Cancelled] and calls == [1]
    finally:
        cancelled.set()
        if worker.ident:
            worker.join(2)
    assert capacity.pending == 0 and capacity.active == 0


@pytest.mark.parametrize("elapsed,allowed", [(0.5, True), (1.0, False), (2.0, False)])
def test_capacity_wakeup_checks_original_deadline(monkeypatch, elapsed, allowed):
    """截止前释放只调用一次，截止时或之后唤醒不启动传输"""
    clock, calls, errors = [0.0], [], []
    waiting, cancelled = threading.Event(), threading.Event()
    monkeypatch.setattr(privacy_gateway, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    capacity = ModelCapacity(parallel=1, waiting=1, wait_seconds=1)

    class Condition(threading.Condition):
        """固定等待者已释放锁的时机"""

        def wait(self, timeout=None):
            """进入实际短等待前通知主线程"""
            waiting.set()
            return super().wait(timeout)

    capacity.condition = Condition()

    def run():
        """计数真正通过模型门的传输入口"""
        try:
            with capacity.enter(cancelled):
                calls.append(1)
        except Exception as exc:
            errors.append(type(exc))

    hold = capacity.enter(threading.Event())
    hold.__enter__()
    held = True
    worker = threading.Thread(target=run)
    try:
        worker.start()
        assert waiting.wait(1)
        with capacity.condition:
            clock[0] = elapsed
            hold.__exit__(None, None, None)
            held = False
        worker.join(1)
        assert not worker.is_alive()
        assert calls == ([1] if allowed else [])
        assert errors == ([] if allowed else [ProviderError])
        assert capacity.active == 0 and capacity.pending == 0
    finally:
        cancelled.set()
        if held:
            hold.__exit__(None, None, None)
        with capacity.condition:
            capacity.condition.notify_all()
        worker.join(1)
