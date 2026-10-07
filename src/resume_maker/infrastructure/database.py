"""短连接 SQLite 访问、即时写事务和数据库初始化"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.data_catalog import CATALOG_SCHEMA, initialize_catalog
from resume_maker.infrastructure.database_policy import DatabasePolicy
from resume_maker.infrastructure.schema_resources import (
    definitions,
    execute_script,
    relational_owners,
    resources,
)
from resume_maker.sdk.records import dump as dump
from resume_maker.sdk.records import now as now
from resume_maker.sdk.records import uid as uid
from resume_maker.sdk.records import unpack as unpack

# SQL 随 Python 包分发，读取位置和当前工作目录无关
SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
# 只接受当前数据库结构
SCHEMA_VERSION = 9


class Connection(sqlite3.Connection):
    """写事务完成后才使业务缓存失效，失败不会提前改写内存状态"""

    def after_commit(self, callback):
        """仅允许在活动事务登记本机缓存操作"""
        if not self.in_transaction:
            raise RuntimeError("缓存回调必须属于活动事务")
        if not hasattr(self, "callbacks"):
            self.callbacks = []
        self.callbacks.append(callback)

    def commit(self):
        """数据库成功提交后按登记顺序同步缓存"""
        super().commit()
        callbacks, self.callbacks = getattr(self, "callbacks", []), []
        for callback in callbacks:
            callback()

    def rollback(self):
        """放弃未提交写入和对应的缓存修改"""
        super().rollback()
        self.callbacks = []


class Database:
    """短连接 SQLite 访问和事务边界，统一 JSON 编解码和配置存储"""

    def __init__(self, path: Path, *, plugins=None, policy=None):
        """校验资料版本后建立所选插件的表，拒绝未迁移的旧库"""
        self.path = path
        self.policy = policy or DatabasePolicy()
        self.activity = None
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, SCHEMA_VERSION} or (
                version == 0
                and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone()
            ):
                raise RuntimeError("数据库结构不受当前程序支持，请先迁移资料或恢复当前版本备份。")
            conn.execute("PRAGMA journal_mode=WAL")
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._install(conn, plugins)
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def _schema_script(self, plugins):
        """读取各插件自行声明的初始结构，不在数据库类维护业务名单"""
        script = resources(definitions() if plugins is None else plugins, "schemas")
        script = script.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ")
        script = script.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ")
        script = script.replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ")
        return script.replace("IF NOT EXISTS IF NOT EXISTS", "IF NOT EXISTS")

    def _install(self, conn, plugins):
        """建表、资料归属和持久引用规则全部加入调用方事务"""
        execute_script(conn, self._schema_script(plugins))
        execute_script(conn, CATALOG_SCHEMA)
        execute_script(conn, resources(relational_owners(conn), "relations"))
        initialize_catalog(conn, plugins)

    def ensure_schemas(self, plugins):
        """按清单补建新启用的结构，已有资料和停用模块的引用规则继续保留"""
        with self.transaction() as conn:
            self._install(conn, plugins)

    def prepare_delete(self, namespace, identifiers, conn):
        """通过持久引用规则先收集阻断原因，再同事务清理依赖资料"""
        identifier = uid()
        conn.execute(
            "INSERT INTO record_operations(id,namespace,identifiers_json,phase) "
            "VALUES (?,?,?,'check')",
            (identifier, namespace, dump(identifiers)),
        )
        row = unpack(
            conn.execute(
                "SELECT blockers_json FROM record_operations WHERE id=?", (identifier,)
            ).fetchone()
        )
        if row["blockers"]:
            raise Problem("\n".join(row["blockers"]), 409)
        conn.execute("UPDATE record_operations SET phase='apply' WHERE id=?", (identifier,))
        conn.execute("DELETE FROM record_operations WHERE id=?", (identifier,))

    def reference(self, namespace, identifier, conn=None):
        """读取由所有者发布的稳定引用快照，消费者不查询插件私有表"""
        if conn is None:
            with self.connect() as connection:
                return self.reference(namespace, identifier, connection)
        row = unpack(
            conn.execute(
                "SELECT value_json FROM record_references WHERE namespace=? AND identifier=?",
                (namespace, identifier),
            ).fetchone()
        )
        return row["value"] if row else None

    def read_session(self, conn):
        """关系后端负责提供只读事务视图，业务不接触 SQLite 授权器"""
        from resume_maker.infrastructure.read_session import ReadSession

        return ReadSession(conn)

    @contextmanager
    def connect(self):
        """创建启用外键约束的短连接并确保异常退出后也释放文件句柄"""
        conn = sqlite3.connect(
            self.path, timeout=self.policy.lock_timeout_seconds, factory=Connection
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        """用即时写事务保护读取后更新操作，成功提交、异常回滚"""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def one(self, sql: str, args=()) -> dict | None:
        """执行参数化查询并返回首条记录或空值"""
        with self.connect() as conn:
            return unpack(conn.execute(sql, args).fetchone())

    def all(self, sql: str, args=()) -> list[dict]:
        """执行参数化查询并把所有记录解码为业务字典"""
        with self.connect() as conn:
            return [unpack(row) for row in conn.execute(sql, args).fetchall()]

    def setting(self, key: str, default=None):
        """读取 JSON 配置，尚未保存时使用调用方提供的默认值"""
        row = self.one("SELECT value_json FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value):
        """在事务中写入配置，已有同名设置时覆盖其值"""
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, dump(value)))

    def event(self, job_id: str, kind: str, data):
        """持久化仍存在任务的进度，项目删除后忽略取消进程的迟到事件"""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO events(job_id,kind,data_json,created_at) "
                "SELECT ?,?,?,? WHERE EXISTS (SELECT 1 FROM jobs WHERE id=?)",
                (job_id, kind, dump(data), now(), job_id),
            )
