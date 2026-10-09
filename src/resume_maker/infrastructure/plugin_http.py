"""插件共享异步连接池，同步入口等待取消和传输清理实际完成"""

import asyncio
import math
import threading
import time
from concurrent.futures import Future
from urllib.parse import urlsplit

import httpx

from resume_maker.sdk.http import HTTPError, HTTPResponse
from resume_maker.sdk.model import Cancelled


class PluginHTTP:
    """每个宿主最多接收 128 个请求，同配额键最多 4 个执行和 32 个等待"""

    def __init__(self, *, transport=None):
        """测试传输可注入，生产连接不继承环境代理或自动跟随重定向"""
        self.transport = transport
        self.lock = threading.RLock()
        self.close_lock = threading.Lock()
        self.loop = None
        self.thread = None
        self.closed = False
        self.pending = 0
        self.quotas = {}
        self.tasks = set()

    def start(self):
        """发布前建立单个传输线程，连接池始终在同一事件循环使用"""
        ready = Future()

        def run():
            """传输线程只处理本宿主的网络任务"""
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.client = httpx.AsyncClient(
                transport=self.transport,
                trust_env=False,
                follow_redirects=False,
                limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
            )
            ready.set_result(None)
            try:
                self.loop.run_forever()
            finally:
                self.loop.close()

        with self.lock:
            if self.closed or self.thread is not None:
                raise HTTPError("HTTP 服务已启动或已停止。")
            self.thread = threading.Thread(target=run, name="plugin-http", daemon=True)
            self.thread.start()
        ready.result(timeout=10)

    def request(
        self,
        method,
        url,
        *,
        deadline,
        cancelled,
        quota,
        headers=None,
        body=None,
        max_bytes=4 * 1024 * 1024,
    ):
        """截止预算涵盖排队和传输，返回前异步请求及取消观察均已结束"""
        target = urlsplit(url)
        if (
            target.scheme != "https"
            or not target.hostname
            or target.username
            or target.password
            or not isinstance(quota, str)
            or not 1 <= len(quota) <= 200
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= 20 * 1024 * 1024
            or type(deadline) not in {int, float}
            or not math.isfinite(deadline)
            or body is not None
            and (not isinstance(body, bytes) or len(body) > 20 * 1024 * 1024)
        ):
            raise HTTPError("HTTP 请求参数不符合公开契约。")
        if cancelled.is_set():
            raise Cancelled("HTTP 请求已取消。")
        if deadline <= time.monotonic():
            raise HTTPError("HTTP 请求已超过截止时间。")
        with self.lock:
            if threading.current_thread() is self.thread:
                raise HTTPError("同步 HTTP 入口不能从传输线程调用。")
            if self.closed or self.loop is None or self.pending >= 128:
                raise HTTPError("HTTP 服务已停止或等待队列已满。")
            self.pending += 1
            future = asyncio.run_coroutine_threadsafe(
                self._request(method, url, deadline, cancelled, quota, headers, body, max_bytes),
                self.loop,
            )
        try:
            return future.result()
        finally:
            with self.lock:
                self.pending -= 1

    async def _request(self, method, url, deadline, cancelled, quota, headers, body, max_bytes):
        """配额键由供应商及账户共同确定，调用者共享同一有界等待队列"""
        current = asyncio.current_task()
        self.tasks.add(current)
        bucket = self.quotas.get(quota)
        if bucket is None:
            if len(self.quotas) >= 256:
                self.tasks.discard(current)
                raise HTTPError("HTTP 配额键数量已达上限。")
            bucket = self.quotas[quota] = {"semaphore": asyncio.Semaphore(4), "pending": 0}
        if bucket["pending"] >= 36:
            self.tasks.discard(current)
            raise HTTPError("供应商配额等待队列已满。")
        bucket["pending"] += 1

        async def observe():
            """取消观察覆盖排队和实际传输，取消只影响当前请求"""
            while not cancelled.is_set():
                await asyncio.sleep(0.05)
            current.cancel()

        observer = asyncio.create_task(observe())
        try:
            async with asyncio.timeout(max(0, deadline - time.monotonic())):
                async with bucket["semaphore"]:
                    async with self.client.stream(
                        method,
                        url,
                        headers={"accept-encoding": "identity", **(headers or {})},
                        content=body,
                        timeout=max(0.001, deadline - time.monotonic()),
                    ) as response:
                        chunks, size = [], 0
                        async for chunk in response.aiter_raw(chunk_size=64 * 1024):
                            size += len(chunk)
                            if size > max_bytes:
                                raise HTTPError("HTTP 响应超过字节上限。")
                            chunks.append(chunk)
                        if cancelled.is_set():
                            raise Cancelled("HTTP 请求已取消。")
                        return HTTPResponse(
                            response.status_code, dict(response.headers), b"".join(chunks)
                        )
        except asyncio.CancelledError:
            raise Cancelled("HTTP 请求已取消或服务已停止。") from None
        except (TimeoutError, httpx.TimeoutException):
            raise HTTPError("HTTP 请求已超过截止时间。") from None
        except (httpx.HTTPError, httpx.InvalidURL):
            raise HTTPError("HTTP 传输失败，请检查供应商连接。") from None
        finally:
            observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)
            bucket["pending"] -= 1
            self.tasks.discard(current)

    async def _shutdown(self):
        """取消后等待所有请求清理，再关闭连接池"""
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.client.aclose()

    def close(self):
        """串行等待关闭完成，避免并发取消打断同一请求的清理"""
        with self.close_lock:
            self._close()

    def _close(self):
        """停止新请求后等待网络线程退出，重复关闭保持安全"""
        with self.lock:
            self.closed = True
            loop, thread = self.loop, self.thread
        if loop is None or thread is None or not thread.is_alive():
            return
        asyncio.run_coroutine_threadsafe(self._shutdown(), loop).result(timeout=30)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=10)
        if thread.is_alive():
            raise HTTPError("HTTP 请求尚未结束，请重试关闭。")
