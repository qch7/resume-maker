import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def uid() -> str:
    return str(uuid4())


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def unpack(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        k.removesuffix("_json"): json.loads(v) if k.endswith("_json") and v else v
        for k, v in dict(row).items()
    }


SCHEMA = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE projects (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, roots_json TEXT NOT NULL,
 profile_json TEXT NOT NULL, head_revision TEXT, archived INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE snapshots (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 fingerprint TEXT NOT NULL, manifest_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE revisions (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 parent_id TEXT REFERENCES revisions(id), snapshot_id TEXT REFERENCES snapshots(id),
 number INTEGER NOT NULL, content_json TEXT NOT NULL, origin TEXT NOT NULL,
 note TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(project_id, number)
);
CREATE TABLE drafts (
 project_id TEXT NOT NULL REFERENCES projects(id),
 base_revision TEXT NOT NULL REFERENCES revisions(id), field TEXT NOT NULL,
 value_json TEXT NOT NULL, version INTEGER NOT NULL, origin TEXT NOT NULL,
 updated_at TEXT NOT NULL, PRIMARY KEY(project_id, base_revision, field)
);
CREATE TABLE conversations (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 title TEXT NOT NULL, provider TEXT NOT NULL DEFAULT 'codex', provider_thread_id TEXT,
 input_draft TEXT NOT NULL DEFAULT '', scope TEXT NOT NULL DEFAULT 'all',
 archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE jobs (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 conversation_id TEXT NOT NULL REFERENCES conversations(id), kind TEXT NOT NULL,
 status TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT,
 error TEXT, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
 request_key TEXT NOT NULL UNIQUE
);
CREATE TABLE messages (
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
 job_id TEXT REFERENCES jobs(id), role TEXT NOT NULL, text TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(job_id, role)
);
CREATE TABLE events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id),
 kind TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE proposals (
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
 job_id TEXT NOT NULL REFERENCES jobs(id), base_revision TEXT REFERENCES revisions(id),
 snapshot_id TEXT REFERENCES snapshots(id), target TEXT NOT NULL, before_json TEXT,
 after_json TEXT NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE templates (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT NOT NULL,
 mapping_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE resumes (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, template_id TEXT REFERENCES templates(id),
 items_json TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE exports (
 id TEXT PRIMARY KEY, resume_id TEXT NOT NULL REFERENCES resumes(id),
 manifest_json TEXT NOT NULL, pages INTEGER, render_error TEXT, created_at TEXT NOT NULL
);
CREATE INDEX ix_conversations_project ON conversations(project_id, updated_at);
CREATE INDEX ix_jobs_status ON jobs(status, created_at);
CREATE INDEX ix_messages_conversation ON messages(conversation_id, created_at);
CREATE INDEX ix_events_job ON events(job_id, id);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("数据库版本高于当前程序，请升级 Resume Maker。")
            if version == 0:
                conn.executescript("BEGIN IMMEDIATE;" + SCHEMA + "PRAGMA user_version=1;COMMIT;")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def one(self, sql: str, args=()) -> dict | None:
        with self.connect() as conn:
            return unpack(conn.execute(sql, args).fetchone())

    def all(self, sql: str, args=()) -> list[dict]:
        with self.connect() as conn:
            return [unpack(row) for row in conn.execute(sql, args).fetchall()]

    def setting(self, key: str, default=None):
        row = self.one("SELECT value_json FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value):
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, dump(value)))

    def event(self, job_id: str, kind: str, data):
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO events(job_id,kind,data_json,created_at) VALUES (?,?,?,?)",
                (job_id, kind, dump(data), now()),
            )
