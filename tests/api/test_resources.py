"""资源下载校验不阻塞事件循环，成功、失败及取消均完整释放租约"""

import asyncio
import threading

import anyio
import pytest

from resume_maker.api.resources import AssetResponse
from resume_maker.core.errors import Problem
from resume_maker.infrastructure.assets import Assets
from resume_maker.infrastructure.database import Database


@pytest.fixture
def resource(tmp_path):
    """发布独立合成资源，不依赖真实用户文件或应用生命周期"""
    assets = Assets(Database(tmp_path / "resume.db"), tmp_path)
    data = b"synthetic attachment\n" * 5000
    record = assets.stage("example", data, "application/octet-stream")
    with assets.db.transaction() as conn:
        assets.publish(conn, record, ["example:file"])
    return assets, record["id"], data


def scope(method="GET", headers=()):
    """构造真实 FileResponse 所需的最小 ASGI 请求"""
    return {
        "type": "http",
        "method": method,
        "headers": list(headers),
        "path": "/synthetic",
        "http_version": "1.1",
        "extensions": {},
    }


async def receive():
    """下载请求没有正文，发送端异常及父任务取消另行控制"""
    return {"type": "http.request", "body": b"", "more_body": False}


@pytest.mark.parametrize("mode", ["get", "head", "range", "send_failure", "corrupt"])
def test_asset_response_preserves_download_and_releases_every_exit(resource, mode):
    """文件头、范围、内容继续由 FileResponse 处理，错误前后不遗留资源占用"""
    assets, identifier, data = resource
    messages = []
    if mode == "corrupt":
        (assets.resource_path(identifier) / "payload").write_bytes(b"changed")

    async def send(message):
        """所有下载消息均在资源租约存续时发送"""
        assert assets.leases[identifier] == 1
        messages.append(message)
        if mode == "send_failure" and message["type"] == "http.response.body":
            raise RuntimeError("synthetic disconnect")

    async def request():
        """用实际 ASGI 响应验证不同下载出口"""
        headers = [(b"range", b"bytes=3-9")] if mode == "range" else []
        response = AssetResponse(assets, identifier, "example.bin", media_type="application/test")
        await response(scope("HEAD" if mode == "head" else "GET", headers), receive, send)

    if mode == "send_failure":
        with pytest.raises(RuntimeError, match="synthetic disconnect"):
            anyio.run(request)
    elif mode == "corrupt":
        with pytest.raises(Problem, match="摘要不匹配"):
            anyio.run(request)
        assert messages == []
    else:
        anyio.run(request)
        assert messages[0]["status"] == (206 if mode == "range" else 200)
        assert (b"content-type", b"application/test") in messages[0]["headers"]
        content = b"".join(message.get("body", b"") for message in messages)
        assert content == (b"" if mode == "head" else data[3:10] if mode == "range" else data)
    assert assets.leases[identifier] == 0


@pytest.mark.parametrize("cancel_kind", ["asyncio", "anyio"])
def test_cancel_during_validation_waits_for_worker_and_returns_lease(
    resource, monkeypatch, cancel_kind
):
    """校验在后台执行，取消须等校验线程结束后回收租约且不能发送迟到正文"""
    assets, identifier, _ = resource
    verifying, release = threading.Event(), threading.Event()
    original, main_thread = assets._verify_file, threading.get_ident()
    sent = []

    def verify(path, expected):
        """可控地暂停真实校验，若错误放在事件循环执行则测试明确失败"""
        assert threading.get_ident() != main_thread
        verifying.set()
        assert release.wait(5)
        return original(path, expected)

    monkeypatch.setattr(assets, "_verify_file", verify)

    async def send(message):
        """取消发生在验证阶段时不能发布响应"""
        sent.append(message)

    async def request():
        """原生任务取消、AnyIO 取消域均必须覆盖实际线程收尾"""
        response = AssetResponse(assets, identifier)
        if cancel_kind == "asyncio":
            task = asyncio.create_task(response(scope(), receive, send))
            try:
                assert await asyncio.to_thread(verifying.wait, 3)
                assert assets.leases[identifier] == 1
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
            finally:
                release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            finished, waiting = anyio.Event(), anyio.CancelScope()

            async def scoped_request():
                """请求取消只影响所属作用域，测试协调器继续释放模拟校验"""
                with waiting:
                    await response(scope(), receive, send)
                finished.set()

            async with anyio.create_task_group() as group:
                group.start_soon(scoped_request)
                try:
                    assert await anyio.to_thread.run_sync(verifying.wait, 3)
                    waiting.cancel()
                    await anyio.sleep(0)
                    assert not finished.is_set()
                finally:
                    release.set()
            assert finished.is_set()

    anyio.run(request)
    assert sent == [] and assets.leases[identifier] == 0


def test_cancel_during_transfer_releases_lease(resource):
    """文件已经开始传输时取消请求仍归还租约"""
    assets, identifier, _ = resource

    async def request():
        """等待首批消息后取消，避免把未开始请求当作下载中断"""
        started = asyncio.Event()

        async def send(message):
            """暂停已持有租约的传输"""
            assert assets.leases[identifier] == 1
            started.set()
            await asyncio.Future()

        task = asyncio.create_task(AssetResponse(assets, identifier)(scope(), receive, send))
        await asyncio.wait_for(started.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    anyio.run(request)
    assert assets.leases[identifier] == 0


def test_lease_factory_failure_keeps_original_exception(resource, monkeypatch):
    """提供方在创建上下文时失败也保留业务异常，不能被任务组包装改变状态码"""
    assets, identifier, _ = resource
    problem = Problem("资源暂不可用。", 409)

    def reject(_identifier):
        """模拟在上下文构造阶段就拒绝资源的提供方"""
        raise problem

    async def send(_message):
        """获取租约失败之前不能发送成功响应"""
        pytest.fail("未取得租约就发送响应")

    async def request():
        """直接观察 ASGI 异常类型，HTTP 异常处理依赖此类型"""
        await AssetResponse(assets, identifier)(scope(), receive, send)

    monkeypatch.setattr(assets, "lease", reject)
    with pytest.raises(Problem) as caught:
        anyio.run(request)
    assert caught.value is problem and assets.leases[identifier] == 0
