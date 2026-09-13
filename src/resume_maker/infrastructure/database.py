"""短连接 SQLite 访问、即时写事务与初始结构迁移。"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def now() -> str:
    """返回毫秒精度的 UTC 时间，供持久化记录和排序统一使用。"""
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def uid() -> str:
    """生成不依赖数据库自增序列的唯一记录标识。"""
    return str(uuid4())


def dump(value: Any) -> str:
    """将数据编码为紧凑 UTF-8 JSON，保留中文并稳定比较草稿内容。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def unpack(row: sqlite3.Row | None) -> dict | None:
    """把 SQLite 行转成字典，解码以 _json 结尾的列并去掉后缀。"""
    if row is None:
        return None
    return {
        k.removesuffix("_json"): json.loads(v) if k.endswith("_json") and v else v
        for k, v in dict(row).items()
    }


# SQL 随 Python 包分发，读取位置与当前工作目录无关。
SCHEMA = (Path(__file__).parent / "migrations" / "001_initial.sql").read_text(encoding="utf-8")
RESUME_DELETIONS = (Path(__file__).parent / "migrations" / "002_resume_deletions.sql").read_text(
    encoding="utf-8"
)
PROJECT_HIERARCHY = (Path(__file__).parent / "migrations" / "003_project_hierarchy.sql").read_text(
    encoding="utf-8"
)
EXPERIENCE_BRANCHES = (
    Path(__file__).parent / "migrations" / "004_experience_branches.sql"
).read_text(encoding="utf-8")


class Database:
    """短连接 SQLite 访问与事务边界，统一 JSON 编解码和配置存储。"""

    def __init__(self, path: Path):
        """初始化数据库文件，启用 WAL 并按版本原子执行增量迁移。"""
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 4:
                raise RuntimeError("数据库版本高于当前程序，请升级 Resume Maker。")
            if version == 0:
                conn.executescript("BEGIN IMMEDIATE;" + SCHEMA + "PRAGMA user_version=1;COMMIT;")
            if version < 2:
                conn.executescript(
                    "BEGIN IMMEDIATE;" + RESUME_DELETIONS + "PRAGMA user_version=2;COMMIT;"
                )
            if version < 3:
                conn.executescript(
                    "BEGIN IMMEDIATE;" + PROJECT_HIERARCHY + "PRAGMA user_version=3;COMMIT;"
                )
            if version < 4:
                conn.executescript(
                    "BEGIN IMMEDIATE;" + EXPERIENCE_BRANCHES + "PRAGMA user_version=4;COMMIT;"
                )

    @contextmanager
    def connect(self):
        """创建启用外键约束的短连接，并确保异常退出后也释放文件句柄。"""
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        """用即时写事务保护读取后更新操作，成功提交、异常回滚。"""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def one(self, sql: str, args=()) -> dict | None:
        """执行参数化查询并返回首条记录，不存在时返回空值。"""
        with self.connect() as conn:
            return unpack(conn.execute(sql, args).fetchone())

    def all(self, sql: str, args=()) -> list[dict]:
        """执行参数化查询并把所有记录解码为业务字典。"""
        with self.connect() as conn:
            return [unpack(row) for row in conn.execute(sql, args).fetchall()]

    def setting(self, key: str, default=None):
        """读取 JSON 配置；尚未保存时使用调用方提供的默认值。"""
        row = self.one("SELECT value_json FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value):
        """在事务中写入配置，已有同名设置时覆盖其值。"""
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, dump(value)))

    def event(self, job_id: str, kind: str, data):
        """把任务进度事件持久化，供 SSE 按递增游标重放。"""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO events(job_id,kind,data_json,created_at) VALUES (?,?,?,?)",
                (job_id, kind, dump(data), now()),
            )
