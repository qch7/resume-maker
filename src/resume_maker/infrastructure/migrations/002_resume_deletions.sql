-- 删除标记独立保存，保留固定版本引用与已导出文件的追溯记录。
CREATE TABLE resume_deletions (
 resume_id TEXT PRIMARY KEY REFERENCES resumes(id), deleted_at TEXT NOT NULL
);
