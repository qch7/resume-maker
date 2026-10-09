"""不透明凭据引用和限用途借用，不进入普通配置或广播"""

import base64
import json
import os
import re
import secrets
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.observability import protect_secrets


class CredentialVault:
    """本机凭据后端协调刷新，原始值只在借用范围内交给可信适配器"""

    def __init__(self, directory: Path | None = None):
        """每个应用实例使用独立引用和撤销集合"""
        self.records, self.lock = {}, threading.RLock()
        self.directory = directory
        self.closed = False

    def save(self, adapter: str, purpose: str, secret: str) -> str:
        """管理入口独立保存密码，每次创建新引用以保留旧计划的凭据"""
        if self.directory is None:
            raise Problem("当前凭据后端不支持持久保存。", 409)
        protect_secrets(secret)
        identifier = "cred." + uuid4().hex
        with self.lock:
            if self.closed:
                raise Problem("凭据服务已停止。", 409)
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.directory.is_symlink() or self.directory.is_junction():
                raise Problem("凭据目录不能使用符号链接。", 409)
            os.chmod(self.directory, 0o700)
            payload = json.dumps(
                {"adapter": adapter, "purpose": purpose, "secret": secret}, ensure_ascii=False
            ).encode("utf-8")
            if os.name == "nt":
                import win32crypt

                payload = win32crypt.CryptProtectData(payload, None, None, None, None, 0)
            path = self.directory / identifier
            with path.open("xb") as stream:
                os.chmod(path, 0o600)
                stream.write(base64.b64encode(payload))
                stream.flush()
                os.fsync(stream.fileno())
        return identifier

    def _persistent(self, identifier):
        """只读取宿主创建的引用，路径和保护格式不由插件提供"""
        if self.directory is None or not re.fullmatch(r"cred\.[a-f0-9]{32}", identifier):
            return None
        path = self.directory / identifier
        if (
            not path.is_file()
            or path.is_symlink()
            or self.directory.is_symlink()
            or self.directory.is_junction()
        ):
            return None
        try:
            payload = base64.b64decode(path.read_bytes(), validate=True)
            if os.name == "nt":
                import win32crypt

                payload = win32crypt.CryptUnprotectData(payload, None, None, None, 0)[1]
            return json.loads(payload)
        except Exception:
            raise Problem("凭据存储无法读取，请重新配置。", 409) from None

    def register(self, adapter, purpose, loader):
        """登记凭据加载器而非在插件配置中存放明文"""
        identifier = secrets.token_urlsafe(24)
        with self.lock:
            if self.closed:
                raise Problem("凭据服务已停止。", 409)
            self.records[identifier] = (adapter, purpose, loader)
        return identifier

    @contextmanager
    def borrow(self, identifier, adapter, purpose):
        """借用时核对适配器及目的，锁协调刷新和撤销"""
        with self.lock:
            if self.closed:
                raise Problem("凭据服务已停止。", 409)
            record = self.records.get(identifier)
            saved = self._persistent(identifier) if record is None else None
            if saved is not None:
                if (saved["adapter"], saved["purpose"]) != (adapter, purpose):
                    raise Problem("凭据引用已撤销或用途不匹配。", 403)
                secret = saved["secret"]
                protect_secrets(secret)
            elif record is None or record[:2] != (adapter, purpose):
                raise Problem("凭据引用已撤销或用途不匹配。", 403)
        if saved is not None:
            yield secret
            return
        with record[2]() as value:
            if isinstance(value, str):
                protect_secrets(value)
            yield value

    def revoke(self, identifier):
        """撤销引用后不再允许创建新借用"""
        with self.lock:
            self.records.pop(identifier, None)
            if self.directory is not None and re.fullmatch(r"cred\.[a-f0-9]{32}", identifier):
                path = self.directory / identifier
                if path.is_file() and not path.is_symlink():
                    path.unlink()

    def close(self):
        """工作区关闭时撤销所有内存引用"""
        with self.lock:
            self.closed = True
            self.records.clear()
