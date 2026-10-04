"""任务授权和平台执行的独立职责"""

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from resume_maker.core.errors import Problem


@dataclass(frozen=True)
class Grant:
    """不可从普通配置构造有效值的短期执行引用"""

    token: str = field(repr=False)
    owner: str
    purpose: str
    generation: int
    expires_at: float
    command: tuple[str, ...]
    cwd: str
    environment_hash: str | None
    materials: tuple[tuple[str, str], ...]
    authorization_epoch: int


def environment_digest(environment):
    """只持有规范环境摘要，不把凭据原文写入授权对象和日志"""
    if environment is None:
        return None
    return hashlib.sha256(json.dumps(environment, sort_keys=True).encode()).hexdigest()


class Execution:
    """只有登记过的有效授权能够进入平台执行入口"""

    def __init__(self, backend):
        """平台进程管理和应用授权分别保存"""
        self.backend, self.grants = backend, {}
        self.lock = threading.RLock()
        self.epochs, self.active = {}, {}

    def authorize(
        self, owner, purpose, generation, *, command, cwd, ttl=300, env=None, materials=()
    ):
        """为通过策略检查的调用签发不可预测的授权引用"""
        grant = Grant(
            secrets.token_urlsafe(32),
            owner,
            purpose,
            generation,
            time.monotonic() + ttl,
            tuple(map(str, command)),
            str(Path(cwd).resolve()),
            environment_digest(env),
            tuple(
                (str(Path(path).resolve()), hashlib.sha256(Path(path).read_bytes()).hexdigest())
                for path in materials
            ),
            self.epochs.get(owner, 0),
        )
        with self.lock:
            self.grants[grant.token] = grant
        return grant

    def revoke(self, grant):
        """撤销后阻止所有新的受控执行"""
        with self.lock:
            self.grants.pop(grant.token, None)

    def revoke_owner(self, owner):
        """权限收紧推进独立授权代次，并通知已开始的执行取消"""
        with self.lock:
            self.epochs[owner] = self.epochs.get(owner, 0) + 1
            for grant, flag in self.active.values():
                if grant.owner == owner:
                    flag.set()

    def execute(self, grant, command, **kwargs):
        """拒绝伪造、过期或撤销授权后调用实际进程后端"""
        with self.lock:
            if (
                self.grants.get(grant.token) != grant
                or grant.expires_at <= time.monotonic()
                or grant.authorization_epoch != self.epochs.get(grant.owner, 0)
            ):
                raise Problem("执行授权已失效。", 403)
            if (
                tuple(map(str, command)) != grant.command
                or str(Path(kwargs["cwd"]).resolve()) != grant.cwd
            ):
                raise Problem("执行命令或目录不符合本轮授权。", 403)
            if grant.environment_hash != environment_digest(kwargs.get("env")):
                raise Problem("执行环境不符合本轮授权。", 403)
            if any(
                hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest
                for path, digest in grant.materials
            ):
                raise Problem("执行材料在授权后发生变化。", 403)
            self.grants.pop(grant.token)
            if flag := kwargs.get("cancelled"):
                self.active[grant.token] = (grant, flag)
        try:
            return self.backend(command, **kwargs)
        finally:
            with self.lock:
                self.active.pop(grant.token, None)


class Sandbox:
    """报告实际保证，所需 OS 隔离无法提供时明确拒绝"""

    def __init__(self, execution, backend):
        """消费执行服务和本地材料会话提供方"""
        self.execution, self.backend = execution, backend

    def capabilities(self):
        """应用材料限制和进程回收不等同于文件及网络强制隔离"""
        return dict(self.backend.capabilities)

    def session(self):
        """统一取得提供方的受管材料目录会话"""
        return self.backend.session()

    def authorize(
        self, owner, purpose, generation, guarantees=(), *, command, cwd, env=None, materials=()
    ):
        """逐项核验任务要求，无法满足时禁止降级放行"""
        supported = self.capabilities()
        missing = [name for name in guarantees if supported.get(name) is not True]
        if missing:
            raise Problem(f"当前 sandbox 无法提供：{'、'.join(missing)}", 409)
        if purpose not in {
            "plugin.worker",
            "plugin.environment",
            "model.readonly-materials",
            "document.local-render",
            "source.authorized-read",
            "native.user-action",
        }:
            raise Problem("未知任务策略。", 403)
        return self.execution.authorize(
            owner, purpose, generation, command=command, cwd=cwd, env=env, materials=materials
        )
