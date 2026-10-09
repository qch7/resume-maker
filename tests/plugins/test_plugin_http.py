"""共享 HTTP 服务的绝对预算、真实取消清理和供应商队列边界"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from resume_maker.infrastructure.plugin_http import PluginHTTP
from resume_maker.sdk.http import HTTPError
from resume_maker.sdk.model import Cancelled


def response(body=b"synthetic"):
    """使用未预读的异步正文模拟真实网络流"""

    class Stream(httpx.AsyncByteStream):
        """单块合成网络流"""

        async def __aiter__(self):
            """真实传输在读取阶段才返回正文"""
            yield body

    return httpx.Response(200, stream=Stream())


def test_http_deadline_and_cancellation_wait_for_transport_cleanup():
    """异步请求真正进入 finally 后，同步调用才报告取消或超时"""
    entered, cleaned = threading.Event(), threading.Event()

    async def handle(_request):
        """可控传输持续等待并记录实际清理结束"""
        entered.set()
        try:
            await asyncio.sleep(10)
        finally:
            await asyncio.sleep(0.02)
            cleaned.set()
        return httpx.Response(200)

    client = PluginHTTP(transport=httpx.MockTransport(handle))
    client.start()
    signal = threading.Event()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                client.request,
                "GET",
                "https://synthetic.invalid/test",
                deadline=time.monotonic() + 5,
                cancelled=signal,
                quota="synthetic",
            )
            assert entered.wait(2)
            signal.set()
            with pytest.raises(Cancelled):
                future.result(timeout=2)
            assert cleaned.is_set()
        entered.clear()
        cleaned.clear()
        with pytest.raises(HTTPError, match="截止"):
            client.request(
                "GET",
                "https://synthetic.invalid/test",
                deadline=time.monotonic() + 0.1,
                cancelled=threading.Event(),
                quota="synthetic",
            )
        assert cleaned.is_set()
    finally:
        client.close()
    assert not client.thread.is_alive()


def test_shared_quota_is_bounded_and_queued_request_can_cancel():
    """两个插件共用配额键时最多四个传输，等待期间也能取消"""
    count = 0
    entered, release = threading.Event(), threading.Event()

    async def handle(_request):
        """前四个传输占据同一供应商额度"""
        nonlocal count
        count += 1
        if count == 4:
            entered.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return response()

    client = PluginHTTP(transport=httpx.MockTransport(handle))
    client.start()
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [
                pool.submit(
                    client.request,
                    "GET",
                    "https://synthetic.invalid",
                    deadline=time.monotonic() + 5,
                    cancelled=threading.Event(),
                    quota="shared-account",
                )
                for _ in range(4)
            ]
            assert entered.wait(2)
            signal = threading.Event()
            queued = pool.submit(
                client.request,
                "GET",
                "https://synthetic.invalid",
                deadline=time.monotonic() + 5,
                cancelled=signal,
                quota="shared-account",
            )
            signal.set()
            with pytest.raises(Cancelled):
                queued.result(timeout=2)
            assert count == 4
            release.set()
            assert all(future.result(timeout=2).body == b"synthetic" for future in futures)
    finally:
        release.set()
        client.close()


def test_http_response_limit_and_closed_service_reject_new_requests():
    """响应体有硬上限，关闭后不得重新启动旧连接池"""
    client = PluginHTTP(transport=httpx.MockTransport(lambda request: response(b"too-large")))
    client.start()
    try:
        with pytest.raises(HTTPError, match="字节上限"):
            client.request(
                "GET",
                "https://synthetic.invalid",
                deadline=time.monotonic() + 2,
                cancelled=threading.Event(),
                quota="synthetic",
                max_bytes=2,
            )
    finally:
        client.close()
    client.close()
    with pytest.raises(HTTPError, match="已停止"):
        client.request(
            "GET",
            "https://synthetic.invalid",
            deadline=time.monotonic() + 2,
            cancelled=threading.Event(),
            quota="synthetic",
        )


def test_concurrent_close_waits_for_active_transfer_cleanup():
    """两个停止请求串行收尾，传输清理结束前不会关闭事件循环"""
    entered, cleaned = threading.Event(), threading.Event()

    async def handle(_request):
        """清理阶段延迟结束，用于核验停止屏障"""
        entered.set()
        try:
            await asyncio.sleep(10)
        finally:
            await asyncio.sleep(0.03)
            cleaned.set()
        return response()

    client = PluginHTTP(transport=httpx.MockTransport(handle))
    client.start()
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            request = pool.submit(
                client.request,
                "GET",
                "https://synthetic.invalid",
                deadline=time.monotonic() + 5,
                cancelled=threading.Event(),
                quota="shared",
            )
            assert entered.wait(2)
            stops = [pool.submit(client.close) for _ in range(2)]
            for stop in stops:
                stop.result(timeout=2)
            assert cleaned.is_set()
            with pytest.raises(Cancelled):
                request.result(timeout=2)
    finally:
        client.close()
    assert not client.thread.is_alive()
