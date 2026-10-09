"""同一读取事务聚合各模块公开的工作台查询"""

import threading

from resume_maker.core.errors import Problem
from resume_maker.sdk.observation import internal
from resume_maker.sdk.records import dump, uid


class Workspace:
    """聚合器持有查询协议，不读取业务表或其他服务内部对象"""

    def __init__(self, storage, *, readers, contributors=None):
        """读取器由组合根明确注入，扩展贡献随作用域撤销"""
        self.db, self.readers = storage, tuple(readers)
        self.contributors = contributors or (lambda: ())
        self.lock = threading.Lock()
        self.observer = None
        self.observe = None
        self.version = None
        self.cached_body = None
        self.etag = None
        self.identity = uid()
        self.serial = 0
        self.stopped = False

    def state(self):
        """所有系统读取和扩展贡献共用一个快照，避免混用不同版本的资料"""
        with self.db.connect() as conn:
            conn.execute("BEGIN")
            state = {"honors": [], "conversations": [], "templates": [], "jobs": []}
            for reader in self.readers:
                state.update(reader(conn))
            for contribute in self.contributors():
                contribute.value(conn, state)
            return state

    @internal
    def poll(self, previous):
        """未变化时省去聚合和正文，数据库及贡献变更立即失效"""
        with self.lock:
            if self.stopped:
                raise Problem("工作台正在停止。", 409)
            observe_factory = getattr(self.db, "change_observer", None)
            if self.observer is None and callable(observe_factory):
                observer = observe_factory()
                self.observe = observer.__enter__()
                self.observer = observer
            contributions = tuple(self.contributors())
            version = (
                self.observe() if self.observe is not None else object(),
                tuple((row.identifier, id(row.value)) for row in contributions),
                object()
                if any(not getattr(row.value, "database_only", False) for row in contributions)
                else None,
            )
            if version != self.version:
                self.cached_body = dump(self.state()).encode("utf-8")
                self.version = version
                self.serial += 1
                self.etag = f'"{self.identity}:{self.serial}"'
            return (None if previous == self.etag else self.cached_body), self.etag

    @internal
    def stop(self):
        """请求排空后关闭提交观察连接并释放聚合缓存"""
        with self.lock:
            self.stopped = True
            self.cached_body = None
            if self.observer is not None:
                self.observer.__exit__(None, None, None)
                self.observer = None
