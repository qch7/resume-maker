-- 当前完整结构，仅对空数据库执行；版本由 database.py 统一登记。
CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE projects (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, roots_json TEXT NOT NULL,
 profile_json TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
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
 updated_at TEXT NOT NULL, document_json TEXT
);
CREATE TABLE exports (
 id TEXT PRIMARY KEY, resume_id TEXT NOT NULL REFERENCES resumes(id),
 manifest_json TEXT NOT NULL, pages INTEGER, render_error TEXT, created_at TEXT NOT NULL
);
CREATE INDEX ix_conversations_project ON conversations(project_id, updated_at);
CREATE INDEX ix_jobs_status ON jobs(status, created_at);
CREATE INDEX ix_messages_conversation ON messages(conversation_id, created_at);
CREATE INDEX ix_events_job ON events(job_id, id);
-- 删除方案仍保留固定引用与导出记录，阻止过期窗口重新写入。
CREATE TABLE resume_deletions (
 resume_id TEXT PRIMARY KEY REFERENCES resumes(id), deleted_at TEXT NOT NULL
);
-- 子项目拥有独立经历和会话，这里只记录分组关系。
CREATE TABLE project_hierarchy (
 project_id TEXT PRIMARY KEY REFERENCES projects(id),
 parent_id TEXT NOT NULL REFERENCES projects(id),
 CHECK (project_id <> parent_id)
);
CREATE INDEX ix_project_hierarchy_parent ON project_hierarchy(parent_id);
CREATE TABLE experience_branches (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 name TEXT NOT NULL COLLATE NOCASE, head_revision TEXT NOT NULL REFERENCES revisions(id),
 is_default INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(project_id, name)
);
CREATE UNIQUE INDEX ix_default_branch ON experience_branches(project_id) WHERE is_default=1;
CREATE TABLE revision_branches (
 revision_id TEXT PRIMARY KEY REFERENCES revisions(id),
 branch_id TEXT NOT NULL REFERENCES experience_branches(id)
);
CREATE INDEX ix_revision_branch ON revision_branches(branch_id);
