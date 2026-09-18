"""短连接 SQLite 访问、即时写事务与数据库初始化"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def now() -> str:
    """返回毫秒精度的 UTC 时间；供持久化记录和排序统一使用"""
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def uid() -> str:
    """生成不依赖数据库自增序列的唯一记录标识"""
    return str(uuid4())


def dump(value: Any) -> str:
    """将数据编码为紧凑 UTF-8 JSON；保留中文并稳定比较草稿内容"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def unpack(row: sqlite3.Row | None) -> dict | None:
    """把 SQLite 行转成字典；解码以 _json 结尾的列并去掉后缀"""
    if row is None:
        return None
    return {
        k.removesuffix("_json"): json.loads(v) if k.endswith("_json") and v else v
        for k, v in dict(row).items()
    }


# SQL 随 Python 包分发；读取位置与当前工作目录无关
SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
# 与早期开发数据库区分且仅支持当前结构且不执行历史迁移
SCHEMA_VERSION = 6


class Database:
    """短连接 SQLite 访问与事务边界；统一 JSON 编解码和配置存储"""

    def __init__(self, path: Path):
        """为空库一次性建立完整结构；已有数据库必须使用当前结构版本"""
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, SCHEMA_VERSION} or (
                version == 0
                and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone()
            ):
                raise RuntimeError("数据库结构不受当前程序支持，请使用新的数据目录。")
            conn.execute("PRAGMA journal_mode=WAL")
            if version == 0:
                conn.executescript(
                    f"BEGIN IMMEDIATE;{SCHEMA}PRAGMA user_version={SCHEMA_VERSION};COMMIT;"
                )

    @contextmanager
    def connect(self):
        """创建启用外键约束的短连接并确保异常退出后也释放文件句柄"""
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        """用即时写事务保护读取后更新操作；成功提交、异常回滚"""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def one(self, sql: str, args=()) -> dict | None:
        """执行参数化查询并返回首条记录且不存在时返回空值"""
        with self.connect() as conn:
            return unpack(conn.execute(sql, args).fetchone())

    def all(self, sql: str, args=()) -> list[dict]:
        """执行参数化查询并把所有记录解码为业务字典"""
        with self.connect() as conn:
            return [unpack(row) for row in conn.execute(sql, args).fetchall()]

    def setting(self, key: str, default=None):
        """读取 JSON 配置；尚未保存时使用调用方提供的默认值"""
        row = self.one("SELECT value_json FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value):
        """在事务中写入配置；已有同名设置时覆盖其值"""
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, dump(value)))

    def event(self, job_id: str, kind: str, data):
        """持久化仍存在任务的进度；项目删除后忽略取消进程的迟到事件"""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO events(job_id,kind,data_json,created_at) "
                "SELECT ?,?,?,? WHERE EXISTS (SELECT 1 FROM jobs WHERE id=?)",
                (job_id, kind, dump(data), now(), job_id),
            )
