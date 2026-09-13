-- 子项目仍是完整项目，单独持有经历、草稿、会话及快照；关联仅用于整体分组。
CREATE TABLE project_hierarchy (
 project_id TEXT PRIMARY KEY REFERENCES projects(id),
 parent_id TEXT NOT NULL REFERENCES projects(id),
 CHECK (project_id <> parent_id)
);
CREATE INDEX ix_project_hierarchy_parent ON project_hierarchy(parent_id);
