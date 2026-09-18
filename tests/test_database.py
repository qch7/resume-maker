"""当前数据库的一次性建库、重开、事务回滚和不支持结构的拒绝行为"""

import sqlite3
from contextlib import closing

import pytest

from resume_maker.infrastructure import database
from resume_maker.infrastructure.database import SCHEMA_VERSION, Database


def test_initialize_complete_schema_and_reopen(tmp_path):
    """空库一次建立全部结构；重开不会重建表或覆盖已存配置"""
    path = tmp_path / "resume.db"
    db = Database(path)
    db.set_setting("test", {"saved": True})
    reopened = Database(path)
    assert reopened.setting("test") == {"saved": True}
    assert reopened.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert reopened.all("PRAGMA foreign_key_check") == []
    assert {row["name"] for row in reopened.all("PRAGMA table_info(resumes)")} >= {
        "items_json",
        "document_json",
        "version",
    }
    assert "head_revision" not in {
        row["name"] for row in reopened.all("PRAGMA table_info(projects)")
    }
    assert reopened.all("SELECT * FROM experience_branches") == []
    assert reopened.all("SELECT * FROM resume_deletions") == []
    assert reopened.all("SELECT * FROM project_hierarchy") == []


@pytest.mark.parametrize("version", [0, 1, 2, 3, 4, 5, SCHEMA_VERSION + 1])
def test_unsupported_database_is_rejected_without_modification(tmp_path, version):
    """未标版本的非空库和不匹配版本均被拒绝；原文件不被升级或重建"""
    path = tmp_path / "unsupported.db"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE preserved (value TEXT)")
        conn.execute("INSERT INTO preserved VALUES ('original')")
        conn.execute(f"PRAGMA user_version={version}")
    original = path.read_bytes()
    with pytest.raises(RuntimeError, match="数据库结构不受当前程序支持"):
        Database(path)
    assert path.read_bytes() == original


def test_failed_initialization_rolls_back_all_tables(tmp_path, monkeypatch):
    """建库途中失败时回滚全部结构；修正后可从空库重新初始化"""
    path = tmp_path / "resume.db"
    with monkeypatch.context() as patch:
        patch.setattr(database, "SCHEMA", database.SCHEMA + "INVALID SQL;")
        with pytest.raises(sqlite3.OperationalError):
            Database(path)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    assert Database(path).one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
