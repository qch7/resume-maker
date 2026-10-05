"""独立实例、分层作用域和候选健康检查的可观察行为"""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType

import pytest

from resume_maker.runtime.graph import PluginError
from resume_maker.runtime.host import Host
from resume_maker.sdk.context import ServiceKey
from resume_maker.sdk.manifest import Manifest


@pytest.fixture
def definitions(monkeypatch):
    """合成插件各自保存计数和资源，只通过声明的能力使用父作用域"""
    module = ModuleType("synthetic_instances")

    def activate(context):
        """登记独立可变状态并记录当前实例选中的上游对象"""
        state = {"value": context.config.get("value", 0), "closed": False}
        for name in context.manifest.requires.get("host", {}):
            state[name] = context.require(ServiceKey(name))
        for name in context.manifest.provides.get("host", {}):
            context.provide(ServiceKey(name), state)
        for point, items in context.manifest.contributes.items():
            for identifier in items:
                context.contribute(point, identifier, state)
        context.effect(lambda: state.update(closed=True))

        def healthy():
            """模拟启动之后才能发现的无效配置"""
            if state["value"] < 0:
                raise PluginError("合成健康检查失败")

        context.health(healthy)

    module.activate = activate
    monkeypatch.setitem(sys.modules, module.__name__, module)
    base = dict(
        title="合成实例",
        version="1.0.0",
        package="synthetic",
        entrypoints={"host": {"mode": "trusted-host", "entry": "synthetic_instances:activate"}},
        config_schema={
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "additionalProperties": False,
        },
    )
    return {
        "example.application": Manifest(
            id="example.application",
            **base,
            instances={"scope": "application"},
            provides={"host": {"application": {}}},
        ),
        "example.counter": Manifest(
            id="example.counter",
            **base,
            instances={"multiple": True},
            requires={"host": {"application": ">=1.0.0"}},
            provides={"host": {"counter": {"cardinality": "many"}}},
            contributes={"example.counters": ["example.counter/value"]},
        ),
        "example.reader": Manifest(
            id="example.reader",
            **base,
            instances={"multiple": True},
            requires={"host": {"counter": ">=1.0.0"}},
            provides={"host": {"reader": {"cardinality": "many"}}},
        ),
        "example.task": Manifest(
            id="example.task",
            **base,
            instances={"scope": "task", "multiple": True},
            requires={"host": {"counter": ">=1.0.0"}},
            provides={"host": {"task": {}}},
        ),
    }


def test_independent_instances_have_explicit_bindings_and_unique_contributions(definitions):
    """同一插件共享定义但状态不串用，两个消费实例分别绑定明确的提供方"""
    specs = [
        {"id": "counter.one", "plugin": "example.counter"},
        {"id": "counter.two", "plugin": "example.counter"},
        {
            "id": "reader.one",
            "plugin": "example.reader",
            "bindings": {"host": {"counter": "counter.one"}},
        },
        {
            "id": "reader.two",
            "plugin": "example.reader",
            "bindings": {"host": {"counter": "counter.two"}},
        },
    ]
    host = Host(
        definitions,
        {"example.application", *(item["id"] for item in specs)},
        set(),
        {"configs": {"counter.one": {"value": 1}, "counter.two": {"value": 2}}},
        instance_specs=specs,
    )
    host.activate()
    host.start()
    one = host.service_values[("reader.one", "reader")]["counter"]
    two = host.service_values[("reader.two", "reader")]["counter"]
    one["value"] = 7
    assert two["value"] == 2
    assert [item.identifier for item in host.collection("example.counters")] == [
        "counter.one/value",
        "counter.two/value",
    ]
    assert host.instances["counter.one"].plugin_id == "example.counter"
    host.close()
    assert one["closed"] and two["closed"]
    assert host.service_values == {} and host.contributions == {}


def test_workspaces_and_tasks_inherit_only_longer_lifetimes(definitions):
    """工作区互不读取状态，任务复用自己的工作区，释放任务不释放父服务"""
    root = Host(definitions, {"example.application"}, set(), scope="application")
    root.activate()
    root.start()
    spec = [{"id": "example.counter", "plugin": "example.counter"}]
    first = root.open_scope("workspace", "first", spec, configs={"example.counter": {"value": 1}})
    second = root.open_scope("workspace", "second", spec, configs={"example.counter": {"value": 2}})
    task = first.open_scope("task", "work", [{"id": "example.task", "plugin": "example.task"}])
    state = task.require(ServiceKey("task"))
    assert state["counter"]["value"] == 1
    assert second.service_values[("example.counter", "counter")]["value"] == 2
    assert task.require(ServiceKey("application")) is root.require(ServiceKey("application"))
    first.close_scope("task", "work")
    assert state["closed"] and not state["counter"]["closed"]
    root.close_scope("workspace", "first")
    assert state["counter"]["closed"]
    assert not second.service_values[("example.counter", "counter")]["closed"]
    root.close()
    assert not root.children
    assert ("example.counter", "counter") not in second.service_values


def test_failed_health_check_never_publishes_child(definitions):
    """候选检查失败撤销所有贡献，父服务继续可用"""
    root = Host(definitions, {"example.application"}, set(), scope="application")
    root.activate()
    with pytest.raises(PluginError, match="健康检查"):
        root.open_scope(
            "workspace",
            "failed",
            [{"id": "example.counter", "plugin": "example.counter"}],
            configs={"example.counter": {"value": -1}},
        )
    assert root.children == {}
    assert not root.require(ServiceKey("application"))["closed"]
    root.close()


def test_task_definitions_require_a_task_scope_and_cannot_expand_permissions(definitions):
    """声明短生命周期不能退化成工作区单例，子插件也不能提升授权"""
    with pytest.raises(PluginError, match="task 作用域"):
        Host(definitions, {"example.task"}, set())
    root = Host(definitions, {"example.application"}, set())
    root.activate()
    changed = definitions["example.counter"].model_copy(
        update={"permissions": ["synthetic.permission"]}
    )
    root.definitions[changed.id] = changed
    with pytest.raises(PluginError, match="父授权"):
        root.open_scope(
            "workspace", "denied", [{"id": changed.id, "plugin": changed.id}], permissions=set()
        )
    root.close()


def test_system_jobs_own_task_instances_until_actual_cleanup(definitions, tmp_path):
    """两个并发任务有独立实例，取消保留租约直到函数和子作用域都退出"""
    from resume_maker.infrastructure.database import Database
    from resume_maker.infrastructure.task_supervisor import TaskSupervisor
    from resume_maker.sdk.tasks import current_task

    host = Host(definitions, {"example.application", "example.counter"}, set())
    host.activate()
    supervisor = TaskSupervisor(
        Database(tmp_path / "tasks.db"), host.task_context, host.prepare_task
    )
    supervisor.start()
    entered, release = threading.Barrier(3), threading.Event()
    states = []

    def work(payload, cancelled):
        """只修改当前任务的对象，并等待测试允许执行器实际退出"""
        context = current_task()
        state = context.require("task.instance", ServiceKey("task"))
        state["value"] = payload
        states.append((context.id, state))
        entered.wait(timeout=5)
        assert release.wait(5)
        return state["value"]

    supervisor.register("example.counter", "run", work)
    records = [
        supervisor.submit(
            "example.counter",
            "run",
            value,
            generation=1,
            idempotency_key=str(value),
            plugin_instances=[{"id": "task.instance", "plugin": "example.task"}],
        )
        for value in (1, 2)
    ]
    try:
        entered.wait(timeout=5)
        supervisor.cancel(records[0]["id"])
        assert len(supervisor.active({"example.task"})) == 2
        assert len(host.children) == 2
        assert sorted(state["value"] for _, state in states) == [1, 2]
        assert host.service_values[("example.counter", "counter")]["value"] == 0
        release.set()
        with supervisor.condition:
            assert supervisor.condition.wait_for(lambda: not supervisor.running, 5)
        assert not host.children
        assert all(state["closed"] for _, state in states)
        assert supervisor.db.setting(f"task:{records[0]['id']}")["result"] is None
        assert supervisor.db.setting(f"task:{records[1]['id']}")["result"] == 2
        with pytest.raises(RuntimeError, match="不在"):
            current_task()
    finally:
        release.set()
        supervisor.stop()
        host.close()


def test_child_cleanup_failure_keeps_application_resources_alive(definitions):
    """子任务清理失败时父服务保留，重试只释放尚未完成的资源"""
    root = Host(definitions, {"example.application"}, set(), scope="application")
    root.activate()
    child = root.open_scope(
        "workspace", "first", [{"id": "example.counter", "plugin": "example.counter"}]
    )
    waiting = [True]

    def stop():
        """模拟执行器尚未完成资源清理"""
        if waiting[0]:
            raise RuntimeError("still-running")

    child.instances["example.counter"].scope.barriers.append(stop)
    application = root.require(ServiceKey("application"))
    with pytest.raises(ExceptionGroup):
        root.close()
    assert not application["closed"]
    assert root.children
    waiting[0] = False
    root.close()
    assert application["closed"] and not root.children


@pytest.mark.parametrize("operation", ["host", "workspace"])
def test_host_shutdown_waits_for_task_before_releasing_child_resources(
    definitions, tmp_path, operation
):
    """退出先取消任务，任务收尾期间父子资源仍可用且作用域只回收一次"""
    from resume_maker.infrastructure.database import Database
    from resume_maker.infrastructure.task_supervisor import TaskSupervisor
    from resume_maker.sdk.tasks import current_task

    root = Host(definitions, {"example.application"}, set(), scope="application")
    root.activate()
    host = root.open_scope(
        "workspace", "first", [{"id": "example.counter", "plugin": "example.counter"}]
    )
    supervisor = TaskSupervisor(
        Database(tmp_path / "tasks.db"), host.task_context, host.prepare_task
    )
    supervisor.start()
    host.instances["example.counter"].scope.barriers.append(supervisor.stop)
    entered, cancelled_seen, release = threading.Event(), threading.Event(), threading.Event()
    observations = {}

    def work(_payload, cancelled):
        """取消及最终返回时观察真实任务作用域的资源是否仍然开放"""
        state = current_task().require("task.instance", ServiceKey("task"))
        observations["state"] = state
        entered.set()
        assert cancelled.wait(10)
        observations["closed_on_cancel"] = state["closed"]
        cancelled_seen.set()
        assert release.wait(10)
        observations["closed_on_exit"] = state["closed"]

    supervisor.register("example.counter", "run", work)
    task = supervisor.submit(
        "example.counter",
        "run",
        {},
        generation=1,
        idempotency_key="shutdown",
        plugin_instances=[{"id": "task.instance", "plugin": "example.task"}],
    )
    with ThreadPoolExecutor(max_workers=1) as closer:
        try:
            assert entered.wait(10)
            closing = closer.submit(
                root.close
                if operation == "host"
                else lambda: root.close_scope("workspace", "first")
            )
            assert cancelled_seen.wait(10)
            assert not observations["closed_on_cancel"]
            assert not observations["state"]["counter"]["closed"]
            assert not closing.done()
            release.set()
            closing.result(timeout=10)
            assert not observations["closed_on_exit"]
            assert observations["state"]["closed"]
            record = supervisor.db.setting(f"task:{task['id']}")
            assert record["state"] == "cancelled" and "error_type" not in record
            assert not host.children
            host.close_scope("task", task["id"])
        finally:
            release.set()
            supervisor.stop()
            root.close()


def test_shutdown_timeout_retains_task_resources_and_rejects_new_work(definitions, tmp_path):
    """停止超时保留全部资源并拒绝新任务，旧执行退出后仍能完成关闭"""
    from resume_maker.core.errors import Problem
    from resume_maker.infrastructure.database import Database
    from resume_maker.infrastructure.task_supervisor import TaskSupervisor
    from resume_maker.sdk.tasks import current_task

    host = Host(definitions, {"example.application", "example.counter"}, set())
    host.activate()
    supervisor = TaskSupervisor(
        Database(tmp_path / "tasks.db"), host.task_context, host.prepare_task
    )
    supervisor.start()
    host.instances["example.counter"].scope.barriers.append(lambda: supervisor.stop(timeout=0.01))
    entered, release = threading.Event(), threading.Event()
    states = []

    def work(_payload, cancelled):
        """故意延后响应取消，收尾时仍需使用父子资源"""
        state = current_task().require("task.instance", ServiceKey("task"))
        states.append(state)
        entered.set()
        assert release.wait(10)
        assert cancelled.is_set() and not state["closed"] and not state["counter"]["closed"]

    supervisor.register("example.counter", "run", work)
    task = supervisor.submit(
        "example.counter",
        "run",
        {},
        generation=1,
        idempotency_key="timeout",
        plugin_instances=[{"id": "task.instance", "plugin": "example.task"}],
    )
    try:
        assert entered.wait(10)
        with pytest.raises(ExceptionGroup):
            host.close()
        assert host.children and not states[0]["closed"]
        assert not states[0]["counter"]["closed"]
        with pytest.raises(Problem):
            supervisor.submit("example.counter", "run", {}, generation=1, idempotency_key="late")
        queue = supervisor.scope("example.counter", 1, {})
        with pytest.raises(Problem):
            queue.submit("late", threading.Event(), lambda: None, {})
        with pytest.raises(Problem), supervisor.db.transaction() as conn:
            queue.prepare(conn, "late", {})
        release.set()
        with supervisor.condition:
            assert supervisor.condition.wait_for(lambda: not supervisor.running, 10)
        record = supervisor.db.setting(f"task:{task['id']}")
        assert record["state"] == "cancelled" and "error_type" not in record
        host.close()
        assert not host.children and states[0]["closed"] and states[0]["counter"]["closed"]
    finally:
        release.set()
        supervisor.stop()
        host.close()
