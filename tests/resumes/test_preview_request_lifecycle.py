"""预览从 HTTP 准入起计时，框架取消仍等待真实收尾"""

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import anyio
import httpx
import pytest
from fastapi import FastAPI

from resume_maker.api.middleware import configure_middleware
from resume_maker.api.schemas import ResumePreviewInput
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.plugin_packages.sys_documents.configuration import Settings
from resume_maker.plugin_packages.sys_documents.routes.resumes import preview_resume, router
from resume_maker.plugin_packages.sys_documents.services.resume_previews import ResumePreviews
from resume_maker.plugin_packages.sys_resume.services.resumes import Resumes
from resume_maker.sdk import documents
from resume_maker.sdk.model import Cancelled, ProviderError
from tests.support.documents import resume_content


async def wait_flag(flag):
    """在调用方的限时作用域内等待线程事件"""
    while not flag.is_set():
        await anyio.sleep(0.005)


async def connected():
    """请求保持连接，取消仅来自框架或截止"""
    return False


@pytest.fixture
def preview_service(catalog, tmp_path):
    """创建只生成合成文件的真实预览服务"""
    calls = []

    def engine(output, *_):
        """隔离文档引擎，只写入几字节"""
        output.write_bytes(b"synthetic")

    def renderer(*_):
        """计数真实渲染启动，不运行 Word"""
        calls.append(1)
        return None, "synthetic"

    service = ResumePreviews(
        Resumes(catalog, storage=catalog.db, assets=catalog.assets),
        tmp_path,
        engine=engine,
        render=renderer,
        settings=Settings(max_preview_requests=1, preview_timeout_seconds=5),
    )
    try:
        yield service, calls
    finally:
        service.stop()


@pytest.mark.parametrize("entrypoint", ["direct", "http"])
def test_http_deadline_and_admission_include_threadpool_queue(
    preview_service, monkeypatch, tmp_path, entrypoint
):
    """池槽被占满时提前拒绝积压，原截止到达后不启动渲染"""
    service, calls = preview_service
    clock = [0.0]
    monkeypatch.setattr(documents, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    occupied, release = threading.Event(), threading.Event()
    failures, results = [], []
    body = ResumePreviewInput(document=resume_content(), items=[])
    request = SimpleNamespace(headers={}, is_disconnected=connected)
    app = FastAPI()
    configure_middleware(app, Config(data_dir=tmp_path / "http", token="synthetic"))
    route = next(route for route in router.routes if route.endpoint is preview_resume)
    app.router.routes.append(route)
    app.state.route_owners = {id(route): "sys.documents"}
    app.state.contexts = {"sys.documents": SimpleNamespace(require=lambda _: service)}

    def occupy():
        """暂时占用共享池，真实等待最多两秒"""
        occupied.set()
        assert release.wait(2)

    async def scenario():
        """使用实际 AnyIO 池和路由测量准入、超时及恢复"""
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = 1
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1",
            headers={"x-resume-token": "synthetic"},
        )

        async def invoke():
            """HTTP 分支执行真实依赖解析、鉴权和路由，不访问网络"""
            if entrypoint == "direct":
                return await preview_resume(service, body, request)
            response = await client.post("/api/resume-previews", json=body.model_dump())
            if response.status_code != 200:
                raise Problem(response.json()["detail"], response.status_code)
            return response.json()

        async def block_worker():
            """占用唯一工作槽位"""
            await anyio.to_thread.run_sync(occupy)

        async def render():
            """保存实际响应或异常，不转换控制行为"""
            try:
                results.append(await invoke())
            except Problem as exc:
                failures.append(exc.status)
            except ProviderError:
                failures.append(502)

        try:
            with anyio.fail_after(3):
                async with anyio.create_task_group() as group:
                    group.start_soon(block_worker)
                    await wait_flag(occupied)
                    for _ in range(3):
                        group.start_soon(render)
                    while (
                        not limiter.statistics().tasks_waiting and len(failures) + len(results) < 3
                    ):
                        await anyio.sleep(0.005)
                    before = (len(service.requests), limiter.statistics().tasks_waiting)
                    clock[0] = 6
                    await anyio.sleep(0.1)
                    expired = (
                        len(service.requests),
                        limiter.statistics().tasks_waiting,
                        len(failures),
                        len(results),
                    )
                    release.set()
                assert before == (1, 1)
                assert expired == (0, 0, 3, 0)
                assert failures.count(429) == 2 and failures.count(502) == 1
                assert results == [] and calls == []
                clock[0] = 7
                await invoke()
                assert calls == [1] and service.requests == {}
        finally:
            release.set()
            limiter.total_tokens = previous
            await client.aclose()

    anyio.run(scenario)


def test_preview_request_scope_is_instance_local(preview_service, tmp_path):
    """取消所属实例的作用域后其他实例仍可生成，重新进入不继承旧取消"""
    service, calls = preview_service
    other = ResumePreviews(
        service.catalog,
        tmp_path / "other",
        engine=service.engine,
        render=service.renderer,
        settings=service.settings,
    )
    cancelled = threading.Event()
    try:
        with service.request_work(cancelled):
            cancelled.set()
            other.render(None, resume_content().model_dump(), [])
            assert calls == [1] and other.requests == {}
            with pytest.raises(Cancelled):
                service.render(None, resume_content().model_dump(), [])
            assert len(service.requests) == 1 and calls == [1]
        assert service.requests == {}
        with service.request_work(threading.Event()):
            service.render(None, resume_content().model_dump(), [])
            assert len(service.requests) == 1 and calls == [1, 1]
        assert service.requests == {}
    finally:
        other.stop()


@pytest.mark.parametrize("cancellation", ["scope", "task", "deadline"])
def test_asgi_cancellation_signals_work_before_cleanup_finishes(
    preview_service, monkeypatch, cancellation
):
    """框架取消及时传到生成器，路由仍等待实际清理返回"""
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    scopes, flags, results, errors = [], [], [], []
    clock = [0.0]
    monkeypatch.setattr(documents, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    service, _ = preview_service
    body = ResumePreviewInput(document=resume_content(), items=[])
    request = SimpleNamespace(headers={}, is_disconnected=connected)

    def renderer(*_):
        """保留真实服务的清理屏障，协作检查在返回后执行"""
        flags.append(documents.current_document_work().cancelled)
        entered.set()
        assert release.wait(2)
        return None, "synthetic"

    monkeypatch.setattr(service, "renderer", renderer)

    async def scenario():
        """独立取消请求作用域，测试线程信号及租约结束时机"""

        async def render():
            """记录请求实际结束，取消后的结果不发布"""
            try:
                with anyio.CancelScope() as scope:
                    scopes.append(scope)
                    if cancellation == "task":
                        scopes[-1] = asyncio.current_task()
                    results.append(await preview_resume(service, body, request))
            except Exception as exc:
                errors.append(type(exc))
            finally:
                finished.set()

        try:
            with anyio.fail_after(3):
                task = asyncio.create_task(render())
                await wait_flag(entered)
                if cancellation == "deadline":
                    clock[0] = 6
                else:
                    scopes[0].cancel()
                await anyio.sleep(0.03)
                if cancellation != "deadline":
                    scopes[0].cancel()
                await anyio.sleep(0.05)
                observed = (flags[0].is_set(), finished.is_set(), len(service.requests))
                with pytest.raises(Problem) as rejected:
                    await preview_resume(service, body, request)
                assert rejected.value.status == 429
                release.set()
                await wait_flag(finished)
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                assert observed == (True, False, 1)
                assert results == []
                assert errors == ([ProviderError] if cancellation == "deadline" else [])
                assert service.requests == {} and service.results == {}
                assert service.pool.entries == {}
                assert not list(Path(service.pool.directory.name).glob("*/resume.docx"))
        finally:
            release.set()

    anyio.run(scenario)


@pytest.mark.parametrize("cancellation", ["scope", "disconnect", "stop"])
def test_cancelling_threadpool_waiter_releases_admission(preview_service, cancellation):
    """未进入工作线程的请求可取消并归还容量，之后仍能正常生成"""
    service, calls = preview_service
    occupied, release, finished = threading.Event(), threading.Event(), threading.Event()
    scopes = []
    disconnected, errors = threading.Event(), []

    async def is_disconnected():
        """在槽位仍被占用时模拟消费者退出"""
        return disconnected.is_set()

    request = SimpleNamespace(headers={}, is_disconnected=is_disconnected)
    body = ResumePreviewInput(document=resume_content(), items=[])

    def occupy():
        """限定占用工作槽位的时间"""
        occupied.set()
        assert release.wait(2)

    async def scenario():
        """实际池等待取消后不执行迟到工作"""
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = 1

        async def block_worker():
            """占用唯一工作槽"""
            await anyio.to_thread.run_sync(occupy)

        async def render():
            """在独立请求取消作用域保持准入租约"""
            try:
                with anyio.CancelScope() as scope:
                    scopes.append(scope)
                    await preview_resume(service, body, request)
            except Exception as exc:
                errors.append(type(exc))
            finally:
                finished.set()

        try:
            with anyio.fail_after(3):
                async with anyio.create_task_group() as group:
                    group.start_soon(block_worker)
                    await wait_flag(occupied)
                    group.start_soon(render)
                    await anyio.sleep(0.03)
                    accepted = len(service.requests)
                    if cancellation == "scope":
                        scopes[0].cancel()
                    elif cancellation == "disconnect":
                        disconnected.set()
                    else:
                        service.stop()
                    await wait_flag(finished)
                    remaining = (len(service.requests), limiter.statistics().tasks_waiting)
                    release.set()
                assert accepted == 1 and remaining == (0, 0)
                assert calls == []
                if cancellation == "stop":
                    with pytest.raises(Problem):
                        await preview_resume(service, body, request)
                    assert calls == []
                else:
                    disconnected.clear()
                    await preview_resume(service, body, request)
                    assert calls == [1]
                assert errors == ([] if cancellation == "scope" else [Cancelled])
        finally:
            release.set()
            limiter.total_tokens = previous

    anyio.run(scenario)
