"""服务器预览排队取消及短暂失败合并"""

import threading
from types import SimpleNamespace

import anyio
import pytest

from resume_maker.api.schemas import ResumePreviewInput
from resume_maker.core.errors import Problem
from resume_maker.infrastructure.execution import Execution, Sandbox
from resume_maker.plugin_packages.ext_word.integrations.word.controlled import ControlledWord
from resume_maker.plugin_packages.sys_documents.configuration import Settings
from resume_maker.plugin_packages.sys_documents.routes.resumes import preview_resume
from resume_maker.plugin_packages.sys_documents.services.resume_previews import ResumePreviews
from resume_maker.plugin_packages.sys_resume.services.resumes import Resumes
from resume_maker.sdk.documents import document_work
from resume_maker.sdk.model import Cancelled, ProviderError
from tests.support.documents import resume_content


def test_cancelled_waiter_never_starts_renderer_and_failure_can_be_forced(catalog, tmp_path):
    """取消等待只撤销所属预览，失败同键复用直到用户明确重试"""
    entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
    calls, errors = [], []

    def engine(output, document, projects):
        """生成受控文件以隔离真实 Word"""
        output.write_bytes(b"docx")

    def renderer(source, output):
        """首个请求等待，其他请求不能因排队取消而启动"""
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return None, "synthetic failure"

    service = ResumePreviews(
        Resumes(catalog, storage=catalog.db, assets=catalog.assets),
        tmp_path,
        engine=engine,
        render=renderer,
    )
    document = resume_content().model_dump()

    def render(flag):
        """记录线程退出原因，确认取消效果而非仅检查取消字段"""
        try:
            service.render(None, document, [], cancelled=flag)
        except Exception as exc:
            errors.append(type(exc))

    first = threading.Thread(target=render, args=(threading.Event(),))
    waiter = threading.Thread(target=render, args=(cancelled,))
    first.start()
    try:
        assert entered.wait(2)
        waiter.start()
        cancelled.set()
        waiter.join(0.5)
        assert not waiter.is_alive() and errors == [Cancelled]
        release.set()
        first.join(2)
        service.render(None, document, [])
        assert len(calls) == 1
        service.render(None, document, [], force=True)
        assert len(calls) == 2
    finally:
        release.set()
        first.join(2)
        if waiter.ident:
            waiter.join(2)
        service.stop()


def test_wait_budget_stops_before_renderer_and_does_not_affect_other_instance(catalog, tmp_path):
    """排队截止不会启动无消费者工作，独立预览实例可以继续使用"""
    calls = []

    def engine(output, document, projects):
        """生成合成 DOCX"""
        output.write_bytes(b"docx")

    def renderer(*args):
        """仅计数真实渲染开始"""
        calls.append(1)
        return None, "synthetic"

    services = [
        ResumePreviews(
            Resumes(catalog, storage=catalog.db, assets=catalog.assets),
            tmp_path / name,
            engine=engine,
            render=renderer,
        )
        for name in ("left", "right")
    ]
    try:
        services[0].lock.acquire()
        with pytest.raises(ProviderError, match="预算"):
            services[0].render(None, resume_content().model_dump(), [], timeout=0.01)
        assert calls == []
        services[1].render(None, resume_content().model_dump(), [])
        assert calls == [1]
    finally:
        if services[0].lock.locked():
            services[0].lock.release()
        for service in services:
            service.stop()


def test_preview_admission_rejects_extra_work_and_stop_cancels_active(catalog, tmp_path):
    """服务端容量满时不启动第二份生成，停止等待实际渲染收尾"""
    entered, release = threading.Event(), threading.Event()
    errors, calls = [], []

    def engine(output, *_):
        """只写入合成文档"""
        output.write_bytes(b"docx")

    def renderer(*_):
        """等待模拟原生资源清理完成"""
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return None, "synthetic"

    service = ResumePreviews(
        Resumes(catalog, storage=catalog.db, assets=catalog.assets),
        tmp_path,
        engine=engine,
        render=renderer,
        settings=Settings(max_preview_requests=1),
    )

    def run():
        """记录已经开始的请求退出原因"""
        try:
            service.render(None, resume_content().model_dump(), [])
        except Exception as exc:
            errors.append(type(exc))

    worker = threading.Thread(target=run)
    stopped = threading.Thread(target=service.stop)
    worker.start()
    try:
        assert entered.wait(2)
        with pytest.raises(Problem, match="队列已满") as failure:
            service.render(None, resume_content().model_dump(), [])
        assert failure.value.status == 429 and calls == [1]
        stopped.start()
        with service.admission:
            flags = list(service.requests.values())
        assert len(flags) == 1 and flags[0].wait(1)
        assert stopped.is_alive()
        release.set()
        worker.join(2)
        stopped.join(2)
        assert errors == [Cancelled] and service.requests == {}
        assert service.results == {} and service.directory is None
    finally:
        release.set()
        worker.join(2)
        if stopped.ident:
            stopped.join(2)
        service.stop()


def test_preview_route_disconnect_waits_for_actual_cleanup():
    """路由将断开传给同步生成器，真实清理结束前保持请求未完成"""
    cancelled_seen, cleanup = threading.Event(), threading.Event()
    calls, results = [], []

    class Service:
        """受控同步预览替身"""

        def render(self, *args, cancelled, force, **kwargs):
            """接到断开后仍需清理资源"""
            calls.append(force)
            assert cancelled.wait(2)
            cancelled_seen.set()
            assert cleanup.wait(2)
            raise Cancelled("synthetic disconnect")

    async def scenario():
        """用异步请求边界验证取消和结果发布的先后顺序"""
        disconnected = False

        async def is_disconnected():
            """仅生成一次可控断开事件"""
            nonlocal disconnected
            disconnected = True
            return disconnected

        async def request():
            """调用实际路由，保存真实异常类型"""
            try:
                await preview_resume(
                    Service(),
                    ResumePreviewInput(document=resume_content(), items=[]),
                    SimpleNamespace(
                        headers={"x-resume-preview-force": "1"}, is_disconnected=is_disconnected
                    ),
                )
            except Exception as exc:
                results.append(type(exc))

        with anyio.fail_after(3):
            async with anyio.create_task_group() as group:
                group.start_soon(request)
                while not cancelled_seen.is_set():
                    await anyio.sleep(0.01)
                assert results == [] and calls == [True]
                cleanup.set()
        assert results == [Cancelled]

    try:
        anyio.run(scenario)
    finally:
        cleanup.set()


def test_document_cancellation_reaches_controlled_word_executor(tmp_path):
    """预览取消传到受管执行边界，授权在真实执行返回后撤销"""
    requested, entered, release = threading.Event(), threading.Event(), threading.Event()
    observed, revoked = [], []

    class Execution:
        """只检查取消参数，不启动任何桌面进程"""

        def execute(self, grant, command, *, cancelled, **kwargs):
            """实际执行期间观察上游取消"""
            entered.set()
            assert requested.wait(2)
            observed.append(cancelled.is_set())
            assert release.wait(2)

        def revoke(self, grant):
            """执行收尾后才撤销授权"""
            revoked.append(grant)

    word = ControlledWord(
        Execution(), SimpleNamespace(authorize=lambda *args, **kwargs: "synthetic"), 1
    )

    def execute():
        """线程中的渲染调用使用当前请求上下文"""
        with document_work(requested, timeout=5, max_bytes=100):
            word.execute(["synthetic"], cwd=tmp_path, timeout=5)

    worker = threading.Thread(target=execute)
    worker.start()
    try:
        assert entered.wait(2)
        requested.set()
        worker.join(0.05)
        assert worker.is_alive() and word.active and revoked == []
        release.set()
        worker.join(2)
        assert observed == [True] and revoked == ["synthetic"] and not word.active
    finally:
        release.set()
        requested.set()
        worker.join(2)
        word.close()


def test_authorization_revocation_cancels_active_word_execution(tmp_path):
    """真实授权层撤销所有者时，预览取消适配器保持原有事件接口"""
    entered, release = threading.Event(), threading.Event()
    observed, failures = [], []

    def backend(command, *, cancelled, **kwargs):
        """平台替身等待授权撤销后检查同一取消对象"""
        entered.set()
        assert release.wait(2)
        observed.append(cancelled.is_set())

    execution = Execution(backend)
    sandbox = Sandbox(execution, SimpleNamespace(capabilities={"process_cleanup": True}))
    word = ControlledWord(execution, sandbox, 1)

    def run():
        """使用真实授权和执行层，不创建进程"""
        try:
            word.execute(["synthetic"], cwd=tmp_path, timeout=2)
        except Exception as exc:
            failures.append(type(exc))

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert entered.wait(1)
        execution.revoke_owner("ext.word")
        assert execution.active and word.active
        release.set()
        worker.join(2)
        assert observed == [True] and failures == []
        assert not execution.active and not word.active
    finally:
        release.set()
        worker.join(2)
        word.close()
