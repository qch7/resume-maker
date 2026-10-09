"""向资料贡献提供同一事务的只读 SQL 查询入口"""

import sqlite3

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import unpack


class ReadSession:
    """阻止来源回调通过查询接口改写正在保存的事务"""

    def __init__(self, conn):
        """引用调用方连接，读会话不拥有提交和关闭权限"""
        self._conn = conn
        self.closed = False

    def all(self, sql, args=()):
        """只允许 SELECT 所需授权操作，拒绝写入及加载扩展"""
        if self.closed:
            raise Problem("读取快照已关闭。", 409)

        def authorize(action, name, _column, _database, _trigger):
            """查询接口只开放普通读取及内置查询函数"""
            allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE}
            if action == sqlite3.SQLITE_FUNCTION:
                return sqlite3.SQLITE_DENY if _column == "load_extension" else sqlite3.SQLITE_OK
            return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY

        self._conn.set_authorizer(authorize)
        try:
            cursor = self._conn.execute(sql, args)
            return [unpack(row) for row in cursor.fetchall()]
        finally:
            self._conn.set_authorizer(None)

    def setting(self, key, default=None):
        """配置读取保持和资料查询同一事务代次"""
        rows = self.all("SELECT value_json FROM settings WHERE key=?", (key,))
        return rows[0]["value"] if rows else default

    def close(self):
        """退出回调后使保留的读取句柄失效"""
        self.closed = True
