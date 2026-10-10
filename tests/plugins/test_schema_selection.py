"""物理最小数据结构和动态启用"""

import sqlite3

import pytest

from resume_maker.infrastructure.database import Database
from resume_maker.plugins.discovery import selection


def test_minimal_has_no_optional_tables_and_enable_preserves_rows(tmp_path):
    """最小库不创建会话和模板表，启用时按所有者补建且重复启用保留资料"""
    selected = selection("minimal")[1]
    db = Database(tmp_path / "resume.db", plugins=selected)
    tables = {row["name"] for row in db.all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {"conversations", "messages", "jobs", "events", "proposals", "templates"} & tables
    assert {"resumes", "revisions", "drafts", "settings", "exports"} <= tables
    db.ensure_schemas(selected | {"ext.template-adapter"})
    with db.transaction() as conn:
        conn.execute("INSERT INTO templates VALUES ('example','合成模板','hash','{}','stamp')")
    db.ensure_schemas(selected)
    db.ensure_schemas(selected | {"ext.template-adapter"})
    assert db.one("SELECT name FROM templates WHERE id='example'")["name"] == "合成模板"
    assert db.all("PRAGMA foreign_key_check") == []


def test_enable_failure_rolls_back_tables_and_reference_rules(tmp_path, monkeypatch):
    """引用规则安装失败不能留下半套插件表，旧资料和提交后回调均受事务保护"""
    from resume_maker.infrastructure import database

    selected = selection("minimal")[1]
    db = Database(tmp_path / "resume.db", plugins=selected)
    db.set_setting("synthetic", {"value": 7})
    before = db.all("SELECT name,type FROM sqlite_master ORDER BY name")
    original = database.resources

    def broken(owners, field):
        """仅在持久引用规则阶段制造失败"""
        return original(owners, field) + ("\nINVALID SQL;" if field == "relations" else "")

    with monkeypatch.context() as patch:
        patch.setattr(database, "resources", broken)
        with pytest.raises(sqlite3.OperationalError):
            db.ensure_schemas(selected | {"ext.template-adapter"})
    assert db.all("SELECT name,type FROM sqlite_master ORDER BY name") == before
    assert db.setting("synthetic") == {"value": 7}
    changes = []
    with pytest.raises(RuntimeError), db.transaction() as conn:
        conn.after_commit(lambda: changes.append("invalidated"))
        raise RuntimeError("synthetic rollback")
    assert changes == []
    with db.transaction() as conn:
        conn.after_commit(lambda: changes.append("committed"))
    assert changes == ["committed"]
