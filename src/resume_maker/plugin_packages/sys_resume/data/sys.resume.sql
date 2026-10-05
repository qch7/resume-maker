CREATE TABLE resumes (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, template_id TEXT,
 items_json TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, document_json TEXT
);
CREATE TABLE resume_deletions (
 resume_id TEXT PRIMARY KEY REFERENCES resumes(id), deleted_at TEXT NOT NULL
);
