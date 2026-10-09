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
