"""日志流真实发送、断开及取消均在请求退出前释放快照"""

import asyncio
import json
import sqlite3
import threading
from contextlib import closing

import anyio
import pytest
from starlette.requests import ClientDisconnect

from resume_maker.infrastructure.activity import ActivityLog
from resume_maker.infrastructure.database import now
from resume_maker.plugin_packages.sys_activity.routes.activity import ActivityQuery, export_activity
from resume_maker.plugin_packages.sys_activity.routes.export_response import ActivityExportResponse


@pytest.fixture
def activity(tmp_path, monkeypatch):
    """建立独立日志及可观测连接，使用合成记录验证真实数据库释放"""
    log = ActivityLog(tmp_path / "activity.sqlite")
    with closing(log.connect()) as conn, conn:
        conn.executemany(
            "INSERT INTO activity(created_at,category,level,source,event,title,"
            "trace_id,payload_json) "
            "VALUES (?,'system','info','synthetic','done',?,'','{}')",
            [(now(), f"synthetic-{index}") for index in range(5)],
        )
    connections, original = [], log.connect

    def connect(**kwargs):
        """记录响应打开的真实连接，稍后确认正常与异常出口均已关闭"""
        conn = original(**kwargs)
        connections.append(conn)
        return conn

    monkeypatch.setattr(log, "connect", connect)
    return log, connections


def scope(version="2.4"):
    """明确流式响应协议版本，兼容旧协议的断开监听路径"""
    return {"type": "http", "asgi": {"spec_version": version}}


async def receive():
    """连接保持等待状态，由发送端失败或请求取消终止下载"""
    await anyio.sleep_forever()


def assert_closed(connections):
    """请求结束时所有快照连接必须关闭，而非等待响应对象被垃圾回收"""
    assert connections
    for conn in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")


@pytest.mark.parametrize("mode", ["complete", "oserror", "runtime_error"])
def test_activity_response_closes_real_snapshot_after_send(activity, mode):
    """正常 JSONL、首块断开发送保留原响应协议，错误不能包装为异常组"""
    log, connections = activity
    messages = []

    class Database:
        """只提供路由实际使用的日志接口"""

        activity = log

    response = export_activity(Database(), ActivityQuery())
    assert isinstance(response, ActivityExportResponse)

    async def send(message):
        """先确认正文确实产生，再模拟不同类型的传输失败"""
        messages.append(message)
        if message["type"] == "http.response.body" and mode != "complete":
            assert message["body"]
            assert connections[-1].in_transaction
            if mode == "oserror":
                raise OSError("synthetic disconnect")
            raise RuntimeError("synthetic send failure")

    async def request():
        """保留响应引用以排除垃圾回收偶然关闭快照的影响"""
        await response(scope(), receive, send)

    if mode == "complete":
        anyio.run(request)
        body = b"".join(message.get("body", b"") for message in messages)
        assert [json.loads(line)["title"] for line in body.splitlines()] == [
            f"synthetic-{index}" for index in range(5)
        ]
    else:
        expected = ClientDisconnect if mode == "oserror" else RuntimeError
        with pytest.raises(expected) as failure:
            anyio.run(request)
        assert type(failure.value) is expected
    headers = dict(messages[0]["headers"])
    assert messages[0]["status"] == 200
    assert headers[b"content-type"] == b"application/x-ndjson"
    assert headers[b"content-disposition"] == b'attachment; filename="system-activity.jsonl"'
    assert_closed(connections)


@pytest.mark.parametrize("cancel_kind", ["asyncio", "anyio"])
@pytest.mark.parametrize("phase", ["next", "send"])
@pytest.mark.parametrize("version", ["2.0", "2.4"])
def test_activity_cancellation_waits_for_reader_before_closing(
    activity, cancel_kind, phase, version
):
    """取消不会抛弃后台 next 或并发关闭生成器，请求作用域一直保留到快照释放"""
    log, connections = activity
    reading, release, closed = threading.Event(), threading.Event(), threading.Event()
    messages = []

    def stream():
        """暂停已经打开快照的首次读取，关闭顺序可直接观察"""
        underlying = log.export()
        try:
            first = next(underlying)
            if phase == "next":
                reading.set()
                assert release.wait(5)
            yield first
            yield from underlying
        finally:
            underlying.close()
            closed.set()

    response = ActivityExportResponse(stream(), media_type="application/x-ndjson")

    async def request():
        """外层 finally 模拟插件请求作用域，响应收尾之前不能释放"""
        send_started, scope_exited = anyio.Event(), anyio.Event()

        async def send(message):
            """只阻塞有实际内容的发送，响应头不能冒充读取完成"""
            messages.append(message)
            if message["type"] == "http.response.body" and phase == "send":
                assert connections[-1].in_transaction
                send_started.set()
                await anyio.sleep_forever()

        async def invoke():
            """请求退出之前同步生成器必须已停止并关闭数据库"""
            try:
                await response(scope(version), receive, send)
            finally:
                assert closed.is_set()
                assert_closed(connections)
                scope_exited.set()

        async def wait_started():
            """等待需要测试的阶段真正开始"""
            if phase == "next":
                assert await anyio.to_thread.run_sync(reading.wait, 3)
            else:
                with anyio.fail_after(3):
                    await send_started.wait()

        if cancel_kind == "asyncio":
            task = asyncio.create_task(invoke())
            try:
                await wait_started()
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0)
                if phase == "next":
                    assert not task.done() and not scope_exited.is_set()
                    assert not closed.is_set()
            finally:
                release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            cancellation = anyio.CancelScope()

            async def scoped():
                """只取消响应所属作用域，协调器负责结束模拟读取"""
                with cancellation:
                    await invoke()

            async with anyio.create_task_group() as group:
                group.start_soon(scoped)
                try:
                    await wait_started()
                    cancellation.cancel()
                    await anyio.sleep(0)
                    if phase == "next":
                        assert not scope_exited.is_set() and not closed.is_set()
                finally:
                    release.set()
        assert scope_exited.is_set()

    anyio.run(request)
    if phase == "next":
        assert not any(message["type"] == "http.response.body" for message in messages)
    assert_closed(connections)


def test_activity_disconnect_waits_for_inflight_read_and_closes_snapshot(activity):
    """旧协议收到实际断开消息后等待后台读取退出，不发布迟到内容或遗留快照"""
    log, connections = activity
    reading, release = threading.Event(), threading.Event()
    messages = []

    def stream():
        """让首条记录在返回事件循环前停留于工作线程"""
        with closing(log.export()) as underlying:
            first = next(underlying)
            reading.set()
            assert release.wait(5)
            yield first
            yield from underlying

    response = ActivityExportResponse(stream())

    async def request():
        """断开监听结束后响应仍须等待正在执行的生成器，随后显式关闭"""
        disconnected = anyio.Event()

        async def receive_disconnect():
            """使用真实 ASGI 断开消息触发框架的流任务取消"""
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            """记录响应消息以检查取消后没有新增正文"""
            messages.append(message)

        task = asyncio.create_task(response(scope("2.0"), receive_disconnect, send))
        try:
            assert await anyio.to_thread.run_sync(reading.wait, 3)
            disconnected.set()
            await anyio.sleep(0)
            await anyio.sleep(0)
            assert not task.done()
            assert connections[-1].in_transaction
        finally:
            release.set()
        await task
        assert_closed(connections)

    anyio.run(request)
    assert not any(message["type"] == "http.response.body" for message in messages)
