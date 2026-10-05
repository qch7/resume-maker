"""读取发行清单声明的数据库资源，建表和持久引用规则共用一个事务"""

import json
import sqlite3
from pathlib import Path


def definitions():
    """只读取随发行安装的清单，外部包仍经停机维护授权执行迁移"""
    root = Path(__file__).resolve().parents[1]
    return {
        value["id"]: value.get("data", {})
        for path in sorted((root / "plugin_packages").glob("*/manifest.json"))
        for value in [json.loads(path.read_text(encoding="utf-8"))]
    }


def resources(selected, field):
    """按所有者读取明确声明的 SQL 文件，拒绝目录外资源"""
    root = Path(__file__).resolve().parents[1]
    scripts = []
    for owner, descriptor in definitions().items():
        if owner not in selected:
            continue
        for name in descriptor.get(field, []):
            path = root / name
            if not path.resolve().is_relative_to(root) or path.suffix != ".sql":
                raise RuntimeError("插件数据结构资源位置无效")
            scripts.append(path.read_text(encoding="utf-8"))
    return "\n".join(scripts)


def relational_owners(conn):
    """停用插件保留已经建立的引用规则，空表也属于已有数据结构"""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {
        owner
        for owner, data in definitions().items()
        if data.get("tables") and set(data["tables"]) <= tables
    }


def execute_script(conn, script):
    """不隐式提交调用方事务，完整触发器作为一条语句执行"""
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            conn.execute(pending)
            pending = ""
    if pending.strip():
        conn.execute(pending)
