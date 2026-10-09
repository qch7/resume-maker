"""有界 JSON RPC 工作进程，故障隔离不冒充 OS 权限隔离"""

import json
import sys
import threading
import time
from uuid import uuid4

from jsonschema import Draft202012Validator

from resume_maker.core.process_environment import EnvironmentPolicy, process_environment
from resume_maker.runtime.graph import PluginError
from resume_maker.sdk.context import ServiceKey


def validate_schema(schema):
    """拒绝需要联网解析的 schema，输入和输出均使用同一公开协议"""
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "$ref" and (not isinstance(value, str) or not value.startswith("#")):
                raise PluginError("RPC schema 不能引用远端资源")
            validate_schema(value)
    elif isinstance(schema, list):
        for item in schema:
            validate_schema(item)


class Worker:
    """每次调用持有独立执行租约和材料会话，可使用独立解释器环境"""

    def __init__(self, context, entry, directory):
        """装载 schema 及授权要求，不运行包内脚本"""
        self.context, self.entry, self.directory = context, entry, directory
        self.execution = context.require(ServiceKey("execution"))
        self.sandbox = context.require(ServiceKey("sandbox"))
        self.condition = threading.Condition()
        self.active = set()
        self.stopped = False
        if "execution.trusted" not in context.manifest.permissions:
            raise PluginError("当前 worker 需要明确授予本机代码信任，不提供 OS 强隔离")
        for method in context.manifest.rpc.values():
            for schema in (method.input_schema, method.output_schema):
                validate_schema(schema)
                Draft202012Validator.check_schema(schema)

    def call(self, method, payload, cancelled=None):
        """核验 DTO 后启动受管进程，退出及结果校验完成前不释放租约"""
        contract = self.context.manifest.rpc.get(method)
        if contract is None:
            raise PluginError("未声明的 worker 操作")
        Draft202012Validator(contract.input_schema).validate(payload)
        cancelled = cancelled or threading.Event()
        request = {
            "rpc_version": 1,
            "id": str(uuid4()),
            "method": method,
            "payload": payload,
            "generation": self.context.generation,
            "instance_id": self.context.instance_id,
            "plugin_id": self.context.plugin_id,
            "scope_id": self.context.scope_id,
            "config": self.context.config,
        }
        encoded = json.dumps(request, ensure_ascii=False)
        if len(encoded.encode()) > 2 * 1024 * 1024:
            raise PluginError("worker 请求超过 2 MB，请改用受控资源引用")
        guarantees = ["process_cleanup"]
        if self.context.manifest.compatibility.get("isolation") == "os":
            guarantees.extend(["os_filesystem_isolation", "os_network_isolation"])
        grant = None
        with self.condition:
            if self.stopped:
                raise PluginError("worker 正在停止")
            self.active.add(cancelled)
        try:
            path = (self.directory / self.entry.entry).resolve()
            if not path.is_relative_to(self.directory):
                raise PluginError("worker 入口越界")
            environment = process_environment(EnvironmentPolicy.WORKER)
            interpreter = (
                self.context.host.bootstrap.get("worker_environments", {})
                .get(self.context.plugin_id, {})
                .get("python", sys.executable)
            )
            with self.sandbox.session() as root:
                environment.update(TEMP=str(root / "control"), TMP=str(root / "control"))
                command = [str(interpreter), "-I", "-X", "utf8", str(path)]
                grant = self.sandbox.authorize(
                    self.context.instance_id,
                    "plugin.worker",
                    self.context.generation,
                    guarantees,
                    command=command,
                    cwd=root,
                    env=environment,
                    materials=[path],
                )
                raw = self.execution.execute(
                    grant,
                    command,
                    cwd=root,
                    env=environment,
                    timeout=contract.timeout_seconds,
                    cancelled=cancelled,
                    stdin=encoded,
                )
            result = json.loads(raw)
            if result.get("rpc_version") != 1 or result.get("id") != request["id"]:
                raise PluginError("worker 响应协议或关联标识不匹配")
            Draft202012Validator(contract.output_schema).validate(result["result"])
            if cancelled.is_set():
                raise PluginError("worker 已取消，迟到结果未发布")
            return result["result"]
        finally:
            if grant is not None:
                self.execution.revoke(grant)
            with self.condition:
                self.active.discard(cancelled)
                self.condition.notify_all()

    def close(self):
        """取消全部活动调用，超时保留资源归属并报告清理失败"""
        deadline = time.monotonic() + self.context.manifest.lifecycle.deactivate_timeout_seconds
        with self.condition:
            self.stopped = True
            for cancelled in self.active:
                cancelled.set()
            while self.active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PluginError("worker 尚未实际结束，资源保留等待清理")
                self.condition.wait(remaining)


def activate_worker(context, entry, directory):
    """为清单能力登记同一 RPC 代理，跨进程对象不能携带数据库连接"""
    worker = Worker(context, entry, directory)
    context.scope.barriers.append(worker.close)
    for method in context.manifest.rpc:
        context.rpc(method, lambda payload, method=method: worker.call(method, payload))
    for name in context.manifest.provides.get("host", {}):
        if name not in context.host.services:
            context.provide(ServiceKey(name), worker)
