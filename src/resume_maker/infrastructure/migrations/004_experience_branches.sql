-- 旧版本全部归入 main，保留修订 ID、父关系、草稿和简历引用。
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
INSERT INTO experience_branches
 SELECT 'main:' || id, id, 'main', head_revision, 1, created_at, updated_at FROM projects
 WHERE head_revision IS NOT NULL;
INSERT INTO revision_branches SELECT id, 'main:' || project_id FROM revisions;
