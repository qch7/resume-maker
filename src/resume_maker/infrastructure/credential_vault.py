"""不透明凭据引用和限用途借用，不进入普通配置或广播"""

import secrets
import threading
from contextlib import contextmanager

from resume_maker.core.errors import Problem


class CredentialVault:
    """本机凭据后端协调刷新，原始值只在借用范围内交给可信适配器"""

    def __init__(self):
        """每个应用实例使用独立引用和撤销集合"""
        self.records, self.lock = {}, threading.RLock()

    def register(self, adapter, purpose, loader):
        """登记凭据加载器而非在插件配置中存放明文"""
        identifier = secrets.token_urlsafe(24)
        with self.lock:
            self.records[identifier] = (adapter, purpose, loader)
        return identifier

    @contextmanager
    def borrow(self, identifier, adapter, purpose):
        """借用时核对适配器及目的，锁协调刷新和撤销"""
        with self.lock:
            record = self.records.get(identifier)
            if record is None or record[:2] != (adapter, purpose):
                raise Problem("凭据引用已撤销或用途不匹配。", 403)
        with record[2]() as value:
            yield value

    def revoke(self, identifier):
        """撤销引用后不再允许创建新借用"""
        with self.lock:
            self.records.pop(identifier, None)

    def close(self):
        """工作区关闭时撤销所有内存引用"""
        with self.lock:
            self.records.clear()
