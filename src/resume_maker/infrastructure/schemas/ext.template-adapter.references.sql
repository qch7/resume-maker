-- 模板插件发布可由系统读取的稳定引用，不要求消费者访问模板私有表
CREATE TRIGGER IF NOT EXISTS template_reference_insert AFTER INSERT ON templates BEGIN
 INSERT OR REPLACE INTO record_references VALUES ('template', NEW.id, 'ext.template-adapter',
 json_object('id',NEW.id,'name',NEW.name,'hash',NEW.hash,'mapping',json(NEW.mapping_json),
 'created_at',NEW.created_at,'_deleted_at',
 (SELECT json_extract(value_json,'$.items.'||json_quote(NEW.id)||'.deleted_at') FROM settings WHERE key='template-library')));
END;
CREATE TRIGGER IF NOT EXISTS template_reference_update AFTER UPDATE ON templates BEGIN
 INSERT OR REPLACE INTO record_references VALUES ('template', NEW.id, 'ext.template-adapter',
 json_object('id',NEW.id,'name',NEW.name,'hash',NEW.hash,'mapping',json(NEW.mapping_json),
 'created_at',NEW.created_at,'_deleted_at',
 (SELECT json_extract(value_json,'$.items.'||json_quote(NEW.id)||'.deleted_at') FROM settings WHERE key='template-library')));
END;
CREATE TRIGGER IF NOT EXISTS template_reference_delete AFTER DELETE ON templates BEGIN
 DELETE FROM record_references WHERE namespace='template' AND identifier=OLD.id AND owner='ext.template-adapter';
END;
CREATE TRIGGER IF NOT EXISTS template_library_reference_insert AFTER INSERT ON settings WHEN NEW.key='template-library' BEGIN
 UPDATE record_references SET value_json=json_set(value_json,'$._deleted_at',
 json_extract(NEW.value_json,'$.items.'||json_quote(identifier)||'.deleted_at'))
 WHERE namespace='template' AND owner='ext.template-adapter';
END;
CREATE TRIGGER IF NOT EXISTS template_library_reference_update AFTER UPDATE ON settings WHEN NEW.key='template-library' BEGIN
 UPDATE record_references SET value_json=json_set(value_json,'$._deleted_at',
 json_extract(NEW.value_json,'$.items.'||json_quote(identifier)||'.deleted_at'))
 WHERE namespace='template' AND owner='ext.template-adapter';
END;
INSERT OR REPLACE INTO record_references
 SELECT 'template',t.id,'ext.template-adapter',
 json_object('id',t.id,'name',t.name,'hash',t.hash,'mapping',json(t.mapping_json),
 'created_at',t.created_at,'_deleted_at',
 (SELECT json_extract(value_json,'$.items.'||json_quote(t.id)||'.deleted_at') FROM settings WHERE key='template-library'))
 FROM templates t;
