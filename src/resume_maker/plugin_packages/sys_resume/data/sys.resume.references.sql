-- 已保存方案的引用保护随数据结构保留，经历模块不读取简历私有表
CREATE TRIGGER IF NOT EXISTS resume_project_guard AFTER INSERT ON record_operations
WHEN NEW.namespace='project' AND NEW.phase='check' BEGIN
 UPDATE record_operations SET blockers_json=json_insert(blockers_json,'$[#]',
 '项目或其子项目正在被简历使用（'||(SELECT group_concat(name,'、') FROM (
 SELECT r.name FROM resumes r WHERE r.id NOT IN (SELECT resume_id FROM resume_deletions)
 AND EXISTS (SELECT 1 FROM json_each(r.items_json) item
 WHERE json_extract(item.value,'$.project_id') IN (SELECT value FROM json_each(NEW.identifiers_json)))
 ORDER BY r.created_at,r.id LIMIT 3))||'），不能删除。请先移除项目并保存组合。')
 WHERE id=NEW.id AND EXISTS (SELECT 1 FROM resumes r
 WHERE r.id NOT IN (SELECT resume_id FROM resume_deletions) AND EXISTS
 (SELECT 1 FROM json_each(r.items_json) item WHERE json_extract(item.value,'$.project_id')
 IN (SELECT value FROM json_each(NEW.identifiers_json))));
END;
