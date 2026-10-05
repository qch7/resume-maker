CREATE TABLE exports (
 id TEXT PRIMARY KEY, resume_id TEXT NOT NULL REFERENCES resumes(id),
 manifest_json TEXT NOT NULL, pages INTEGER, render_error TEXT, created_at TEXT NOT NULL
);
