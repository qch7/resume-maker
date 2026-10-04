"""在现有事务存储上提供固定命名空间的实例资料，不向插件暴露连接"""

import json
import threading
from contextlib import contextmanager
from copy import deepcopy

from resume_maker.core.errors import Problem
from resume_maker.sdk.storage import StoredValue


class InstanceDataStore:
    """普通实例持久保存，任务实例只持有本轮临时状态"""

    def __init__(self, db, owner, scope_id, temporary=False):
        """身份由运行时提供，插件不能在后续调用中改写命名空间"""
        self.db, self.owner = db, owner
        self.prefix = (
            "plugin-instance:" + json.dumps([scope_id, owner], separators=(",", ":")) + ":"
        )
        self.temporary = {} if temporary else None
        self.closed = False
        self.lock = threading.RLock()

    def close(self):
        """旧句柄立即失效，持久内容保留供重新启用和备份恢复"""
        with self.lock:
            self.closed = True
            if self.temporary is not None:
                self.temporary.clear()

    @contextmanager
    def transaction(self):
        """异常撤销全部修改，关闭句柄等待正在提交的事务完成"""
        with self.lock:
            if self.closed:
                raise Problem("插件实例资料句柄已关闭。", 409)
            if self.temporary is not None:
                candidate = deepcopy(self.temporary)
                session = InstanceTransaction(self.prefix, values=candidate)
                try:
                    yield session
                    self.temporary = candidate
                finally:
                    session.closed = True
            else:
                with self.db.transaction() as connection:
                    session = InstanceTransaction(self.prefix, connection=connection)
                    try:
                        yield session
                    finally:
                        session.closed = True

    def get(self, key):
        """按当前键读取独立值和版本，返回对象不引用存储内部状态"""
        with self.transaction() as transaction:
            return transaction.get(key)

    def set(self, key, value, expected_version):
        """单键更新复用同事务比较协议"""
        with self.transaction() as transaction:
            return transaction.set(key, value, expected_version)

    def delete(self, key, expected_version):
        """明确删除保留版本标记"""
        with self.transaction() as transaction:
            return transaction.delete(key, expected_version)


class InstanceTransaction:
    """只提供当前实例的 JSON 键操作，事务退出后对象不可复用"""

    def __init__(self, prefix, connection=None, values=None):
        """临时和持久后端使用相同的版本协议"""
        self.prefix, self.connection, self.values = prefix, connection, values
        self.closed = False

    def identity(self, key):
        """键视作普通文本，长度受控且不接受路径或 SQL 片段参数"""
        if self.closed:
            raise Problem("插件资料事务已结束。", 409)
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise Problem("插件资料键长度无效。", 422)
        return self.prefix + key

    def get(self, key):
        """不存在的键和删除标记保持不同语义"""
        identity = self.identity(key)
        if self.connection is not None:
            row = self.connection.execute(
                "SELECT value_json FROM settings WHERE key=?", (identity,)
            ).fetchone()
            value = json.loads(row[0]) if row else None
        else:
            value = deepcopy(self.values.get(identity))
        return StoredValue(**value) if value else StoredValue(0)

    def write(self, key, value, expected_version, deleted):
        """先校验完整 JSON 和版本，再更新同一事务中的键"""
        identity = self.identity(key)
        if type(expected_version) is not int or expected_version < 0:
            raise Problem("插件资料版本无效。", 422)
        previous = self.get(key)
        if previous.version != expected_version:
            raise Problem("插件资料已变化，请重新读取后再保存。", 409)
        record = {"version": previous.version + 1, "value": value, "deleted": deleted}
        encoded = json.dumps(record, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode()) > 1024 * 1024:
            raise Problem("插件资料超过 1 MB，请使用资源引用。", 422)
        if self.connection is not None:
            self.connection.execute(
                "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) "
                "DO UPDATE SET value_json=excluded.value_json",
                (identity, encoded),
            )
        else:
            self.values[identity] = json.loads(encoded)
        return StoredValue(**json.loads(encoded))

    def set(self, key, value, expected_version):
        """保存值，包括明确的 JSON null"""
        return self.write(key, value, expected_version, False)

    def delete(self, key, expected_version):
        """删除标记递增版本，防止旧副本悄悄恢复已删内容"""
        return self.write(key, None, expected_version, True)
