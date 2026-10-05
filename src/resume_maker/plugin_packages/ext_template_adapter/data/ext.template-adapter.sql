CREATE TABLE templates (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT NOT NULL,
 mapping_json TEXT NOT NULL, created_at TEXT NOT NULL
);
