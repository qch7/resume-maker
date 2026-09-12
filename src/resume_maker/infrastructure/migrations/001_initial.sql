-- 初始结构（user_version = 1）；已有数据库不重复执行。
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
