-- AI 所有者声明项目删除时的排空检查和同事务清理，停用后规则仍保留
CREATE TRIGGER IF NOT EXISTS conversation_project_guard AFTER INSERT ON record_operations
WHEN NEW.namespace='project' AND NEW.phase='check' BEGIN
 UPDATE record_operations SET blockers_json=json_insert(blockers_json,'$[#]',
 '项目或其子项目仍有 AI 任务进行中，请等待完成或取消后再删除。')
 WHERE id=NEW.id AND EXISTS (SELECT 1 FROM jobs
 WHERE project_id IN (SELECT value FROM json_each(NEW.identifiers_json))
 AND status IN ('queued','running'));
END;
CREATE TRIGGER IF NOT EXISTS conversation_project_remove AFTER UPDATE OF phase ON record_operations
WHEN NEW.namespace='project' AND NEW.phase='apply' AND OLD.phase='check'
AND json_array_length(NEW.blockers_json)=0 BEGIN
 DELETE FROM proposals WHERE conversation_id IN (SELECT id FROM conversations
 WHERE project_id IN (SELECT value FROM json_each(NEW.identifiers_json)));
 DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations
 WHERE project_id IN (SELECT value FROM json_each(NEW.identifiers_json)));
 DELETE FROM events WHERE job_id IN (SELECT id FROM jobs
 WHERE project_id IN (SELECT value FROM json_each(NEW.identifiers_json)));
 DELETE FROM jobs WHERE project_id IN (SELECT value FROM json_each(NEW.identifiers_json));
 DELETE FROM conversations WHERE project_id IN (SELECT value FROM json_each(NEW.identifiers_json));
END;
