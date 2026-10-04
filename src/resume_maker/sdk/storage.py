"""插件实例的数据接口，提供版本比较和同事务多键更新"""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol


class Rows(Protocol):
    """参数化查询的结果，记录支持列名和列序号读取"""

    rowcount: int

    def fetchone(self):
        """返回下一条记录，没有记录时返回空值"""
        ...

    def fetchall(self):
        """读取剩余记录，供事务内固定快照"""
        ...

    def __iter__(self):
        """依次读取查询结果"""
        ...


class Transaction(Protocol):
    """工作区关系存储会话，参数使用问号占位且 JSON 列按公开规则编码"""

    def execute(self, statement: str, parameters=()) -> Rows:
        """在当前快照执行参数化语句，禁止跨线程保留会话"""
        ...

    def after_commit(self, callback) -> None:
        """提交成功后更新本机缓存，回滚时丢弃回调"""
        ...


class RelationalStore(Protocol):
    """业务存储契约，写事务串行提交，异常整体回滚"""

    activity: Any

    def read_session(self, conn):
        """提供当前事务的只读视图，关闭后旧句柄失效"""
        ...

    def prepare_delete(self, namespace, identifiers, conn):
        """由持久所有权规则核验并清理外部引用，失败撤销整个事务"""
        ...

    def reference(self, namespace, identifier, conn=None):
        """读取所有者发布的稳定资料引用，支持共享事务快照"""
        ...

    def ensure_schemas(self, plugins):
        """按已安装定义初始化所选模块的空数据结构，已有资料不重建"""
        ...

    def connect(self) -> AbstractContextManager[Transaction]:
        """打开短会话，读取快照须显式开始事务"""
        ...

    def transaction(self) -> AbstractContextManager[Transaction]:
        """在读取之前取得写锁，成功提交或异常整体撤销"""
        ...

    def one(self, statement: str, parameters=()) -> dict | None:
        """查询首条记录并解码公开 JSON 列"""
        ...

    def all(self, statement: str, parameters=()) -> list[dict]:
        """查询全部记录并解码公开 JSON 列"""
        ...

    def setting(self, key: str, default=None):
        """读取共享系统设置，未保存时返回默认值"""
        ...

    def set_setting(self, key: str, value) -> None:
        """以独立写事务保存设置"""
        ...


@dataclass(frozen=True)
class StoredValue:
    """删除保留版本标记，旧窗口不能重建已经删除的资料"""

    version: int
    value: Any = None
    deleted: bool = False


class InstanceData(Protocol):
    """每个句柄固定实例命名空间，关闭插件后旧句柄失效"""

    def get(self, key: str) -> StoredValue:
        """读取独立副本，未保存的键版本为零"""
        ...

    def set(self, key: str, value: Any, expected_version: int) -> StoredValue:
        """在版本仍匹配时保存合法 JSON，冲突保持原资料"""
        ...

    def delete(self, key: str, expected_version: int) -> StoredValue:
        """独立删除操作保留版本，不混淆空值和删除"""
        ...

    def transaction(self):
        """整组键更新共用同一事务，异常时整体撤销"""
        ...
