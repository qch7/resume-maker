"""模板原件、分析结果和人工草稿在重启及恢复后保持对应"""

from zipfile import ZipFile

from test_template_analysis import TemplateProvider, completed, simple_document, simple_template

from resume_maker.infrastructure.database import Database, dump
from resume_maker.infrastructure.storage import create_backup, restore_backup
from resume_maker.services.catalog import Catalog
from resume_maker.services.templates.tasks import Templates
from resume_maker.services.workspace_storage import WorkspaceStorage


def test_analysis_and_manual_mapping_survive_backup(catalog, tmp_path):
    """原文件删除和浏览器缓存清空后仍能继续核对，备份不携带模型工作区"""
    root = catalog.db.path.parent
    source = tmp_path / "template.docx"
    simple_template(source)
    service = Templates(catalog, root, TemplateProvider())
    task = completed(service, service.analyze(source, simple_document())["id"])
    assert task["status"] == "completed"
    source.unlink()
    storage = WorkspaceStorage(catalog.db)
    manual = {"plan": task["plan"], "name": "人工改名", "feedback": "待核对的说明"}
    storage.save(f"rm.template.editor.{task['id']}", dump(manual), 0)
    storage.save("rm.template.analysis", task["id"], 0)
    private = root / "workspaces" / f"template-{task['id']}" / "private-cli-config"
    private.write_text("synthetic credential excluded")
    archive = create_backup(catalog.db, root)
    with ZipFile(archive) as saved:
        assert not any(name.startswith("workspaces/") for name in saved.namelist())
        assert f"template-drafts/{task['id']}/uploaded.docx" in saved.namelist()
    target = tmp_path / "restored"
    restore_backup(archive, target)
    restored_catalog = Catalog(Database(target / "resume.db"))
    restored = Templates(restored_catalog, target, TemplateProvider())
    assert restored.get(task["id"])["plan"] == task["plan"]
    assert restored.source(task["id"]).is_file()
    assert restored.list_tasks()[0]["id"] == task["id"]
    assert WorkspaceStorage(restored_catalog.db).state()["values"][
        f"rm.template.editor.{task['id']}"
    ]["value"] == dump(manual)


def test_interrupted_analysis_requires_explicit_retry(catalog, tmp_path):
    """重启标记中断且不自动调用模型，重试从留存原件生成新任务"""
    source = tmp_path / "template.docx"
    simple_template(source)
    root = catalog.db.path.parent
    service = Templates(catalog, root, TemplateProvider())
    task = completed(service, service.analyze(source, simple_document())["id"])
    record = catalog.db.setting(f"template-task:{task['id']}")
    record["task"]["status"] = "running"
    record["task"]["plan"] = None
    catalog.db.set_setting(f"template-task:{task['id']}", record)
    provider = TemplateProvider()
    restarted = Templates(catalog, root, provider)
    assert not provider.calls
    interrupted = restarted.get(task["id"])
    assert interrupted["status"] == "failed"
    assert interrupted["phase"] == "interrupted"
    source.unlink()
    retry = completed(restarted, restarted.retry(task["id"], simple_document(), [])["id"])
    assert retry["status"] == "completed"
    assert retry["id"] != task["id"]
