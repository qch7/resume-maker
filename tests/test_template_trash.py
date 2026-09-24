"""模板回收站、引用保护、到期清理和永久文件删除的完整行为"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_resume_previews import register_template
from test_template_mapping import resume_content

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.domain.templates import TEMPLATE_LIBRARY_KEY
from resume_maker.infrastructure.database import dump
from resume_maker.services.templates.library import TemplateLibrary


def age_item(service, identifier, stamp):
    """直接修改夹具的回收时间"""
    state = service.db.setting(TEMPLATE_LIBRARY_KEY)
    state["items"][identifier]["deleted_at"] = stamp.isoformat()
    service.db.set_setting(TEMPLATE_LIBRARY_KEY, state)


def test_recycle_restore_and_permanent_delete_api(tmp_path):
    """取消不产生请求，移入后不可选用，恢复保留收藏，永久删除实际文件和保存记录"""
    config = Config(data_dir=tmp_path / "data", token="test")
    headers = {"x-resume-token": "test"}
    with TestClient(create_app(config)) as client:
        services = client.app.state.services
        source = register_template(services.catalog, config.data_dir)
        original = source.read_bytes()
        category = services.template_library.create_category("示例")["categories"][0]["id"]
        services.template_library.update("mapped", {"liked": True, "category_id": category})
        assert client.delete("/api/template-library/items/mapped").status_code == 401
        recycled = client.delete("/api/template-library/items/mapped", headers=headers)
        assert recycled.status_code == 200
        item = recycled.json()["items"]["mapped"]
        assert item["deleted_at"] and item["liked"] and item["category_id"] == category
        assert source.read_bytes() == original
        assert client.post("/api/templates/mapped/edit", headers=headers).status_code == 409
        assert (
            client.patch(
                "/api/template-library/items/mapped", headers=headers, json={"liked": False}
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/resumes",
                headers=headers,
                json={"name": "过期窗口", "template_id": "mapped", "items": []},
            ).status_code
            == 409
        )
        assert (
            client.delete("/api/template-library/items/mapped", headers=headers).json()
            == recycled.json()
        )
        restored = client.post("/api/template-library/items/mapped/restore", headers=headers).json()
        assert restored["items"]["mapped"] == {"liked": True, "category_id": category}
        assert client.post("/api/templates/mapped/edit", headers=headers).status_code == 200
        document = resume_content().model_dump()
        document["personal"]["website"] = "https://example.test"
        adapted = client.post(
            "/api/templates/mapped/edit",
            headers=headers,
            json={"document": document, "items": []},
        )
        assert adapted.status_code == 200
        draft_key = f"rm.template.editor.{adapted.json()['id']}"
        services.workspace_storage.save(draft_key, "synthetic manual draft", 0)
        adapted_source = services.templates.source(adapted.json()["id"])
        assert adapted_source.read_bytes() != original
        assert (
            client.delete(
                "/api/template-library/items/mapped?permanent=true", headers=headers
            ).status_code
            == 409
        )
        services.template_library.delete("mapped")
        removed = client.delete(
            "/api/template-library/items/mapped?permanent=true", headers=headers
        )
        assert removed.status_code == 200 and removed.json()["templates"] == []
        assert "mapped" not in removed.json()["items"]
        assert not source.parent.exists()
        assert not services.db.one("SELECT * FROM templates WHERE id='mapped'")
        assert not services.templates.tasks
        assert not adapted_source.parent.exists()
        assert not services.db.all("SELECT * FROM settings WHERE key LIKE 'template-task:%'")
        assert services.workspace_storage.state()["values"][draft_key]["value"] is None
        with pytest.raises(Problem, match="其他窗口"):
            services.workspace_storage.save(draft_key, "stale manual draft", 1)
        assert (
            client.delete(
                "/api/template-library/items/mapped?permanent=true", headers=headers
            ).status_code
            == 404
        )


def test_used_templates_and_builtin_cannot_be_removed(catalog, tmp_path):
    """所有保存方案的固定引用均受保护，包括保留历史导出的已删除方案"""
    source = register_template(catalog, tmp_path / "data")
    service = TemplateLibrary(catalog, tmp_path / "data")
    resume = catalog.save_resume("正在使用", "mapped", [], document=resume_content())
    before = source.read_bytes(), catalog.template("mapped"), service.state()
    for permanent in (False, True):
        with pytest.raises(Problem, match="不能删除"):
            service.delete("mapped", permanent)
        with pytest.raises(Problem, match="内置"):
            service.delete("builtin", permanent)
    catalog.delete_resume(resume["id"], resume["version"])
    with pytest.raises(Problem, match="正在使用"):
        service.delete("mapped")
    assert (source.read_bytes(), catalog.template("mapped"), service.state()) == before


def test_exact_deadline_and_restoration_cancel_cleanup(catalog, tmp_path):
    """不足三十天不清理，到期精确清理，恢复后旧清理任务不能删除已恢复项"""
    source = register_template(catalog, tmp_path / "data")
    service = TemplateLibrary(catalog, tmp_path / "data")
    service.delete("mapped")
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    age_item(service, "mapped", stamp)
    service.purge_expired(stamp + timedelta(days=30) - timedelta(microseconds=1))
    assert source.exists()
    service.restore("mapped")
    service.delete("mapped", permanent=True, cutoff=stamp)
    assert source.exists()
    service.delete("mapped")
    age_item(service, "mapped", stamp)
    service.purge_expired(stamp + timedelta(days=30))
    assert not source.exists()
    assert service.state()["templates"] == []


def test_restart_cleans_expired_without_opening_library(tmp_path):
    """应用启动自动补清到期项并启动定时器，应用退出回收线程"""
    config = Config(data_dir=tmp_path / "data", token="test")
    app = create_app(config)
    source = register_template(app.state.services.catalog, config.data_dir)
    service = app.state.services.template_library
    service.delete("mapped")
    age_item(service, "mapped", datetime.now(UTC) - timedelta(days=31))
    with TestClient(app):
        assert not source.parent.exists()
        assert service.worker.is_alive()
    assert not service.worker.is_alive()


def test_permanent_cleanup_keeps_shared_artifacts_and_external_source(catalog, tmp_path):
    """永久删除仅清理模板专属目录、缓存和缩略图"""
    root = tmp_path / "data"
    source = register_template(catalog, root)
    record = catalog.template("mapped")
    external = tmp_path / "user-original.docx"
    external.write_bytes(source.read_bytes())
    exclusive = root / "workspaces" / "template-exclusive"
    shared = root / "workspaces" / "template-shared"
    for directory in (exclusive, shared):
        directory.mkdir(parents=True)
        (directory / "evidence.json").write_text("recognition")
    cache = root / "template-cache" / "plan.json"
    cache.parent.mkdir()
    cache.write_text(dump(record["mapping"]["plan"]), encoding="utf-8")
    thumbnail = root / "templates" / ".previews" / record["hash"]
    thumbnail.mkdir(parents=True)
    (thumbnail / "page-1.png").write_bytes(b"preview")
    artifacts = [directory.relative_to(root).as_posix() for directory in (exclusive, shared)]
    with catalog.db.transaction() as conn:
        mapping = {**record["mapping"], "artifacts": artifacts}
        conn.execute("UPDATE templates SET mapping_json=? WHERE id='mapped'", (dump(mapping),))
        conn.execute(
            "INSERT INTO templates VALUES (?,?,?,?,?)",
            (
                "other",
                "共享模板",
                record["hash"],
                dump({**record["mapping"], "artifacts": [artifacts[1]]}),
                record["created_at"],
            ),
        )
    other = root / "templates" / "other" / "template.docx"
    other.parent.mkdir()
    other.write_bytes(source.read_bytes())
    service = TemplateLibrary(catalog, root)
    service.delete("mapped")
    service.delete("mapped", permanent=True)
    assert not source.parent.exists() and not exclusive.exists()
    assert shared.exists() and thumbnail.exists() and cache.exists() and external.exists()
    service.delete("other")
    service.delete("other", permanent=True)
    assert not shared.exists() and not thumbnail.exists() and not cache.exists()
    assert external.exists()


def test_failed_file_cleanup_stays_in_trash_for_retry(catalog, tmp_path, monkeypatch):
    """文件占用不能返回假成功或删除数据库记录，解除占用后可完成重试"""
    root = tmp_path / "data"
    source = register_template(catalog, root)
    service = TemplateLibrary(catalog, root)
    service.delete("mapped")
    import shutil

    original = shutil.rmtree

    def locked(path):
        """模拟目标模板目录被 Word 锁定"""
        raise PermissionError("locked")

    monkeypatch.setattr("resume_maker.services.templates.cleanup.shutil.rmtree", locked)
    with pytest.raises(Problem, match="重试"):
        service.delete("mapped", permanent=True)
    assert source.exists() and service.state()["items"]["mapped"]["deleted_at"]
    monkeypatch.setattr("resume_maker.services.templates.cleanup.shutil.rmtree", original)
    service.delete("mapped", permanent=True)
    assert not source.exists()


def test_recycle_and_save_cannot_create_a_dangling_reference(catalog, tmp_path):
    """并发保存和移入只允许一个成功，数据库不会产生引用回收站模板的简历"""
    register_template(catalog, tmp_path / "data")
    service = TemplateLibrary(catalog, tmp_path / "data")
    with ThreadPoolExecutor(max_workers=2) as pool:
        operations = [
            pool.submit(service.delete, "mapped"),
            pool.submit(catalog.save_resume, "并发方案", "mapped", [], document=resume_content()),
        ]
        results = []
        for operation in operations:
            try:
                results.append(operation.result())
            except Problem:
                results.append(None)
    assert sum(result is not None for result in results) == 1
    assert not (
        catalog.db.all("SELECT * FROM resumes")
        and service.state()["items"].get("mapped", {}).get("deleted_at")
    )


def test_cleanup_refuses_paths_outside_data_before_deleting(catalog, tmp_path):
    """异常产物索引不能删除外部文件，检查失败时模板目录也保持完整"""
    root = tmp_path / "data"
    source = register_template(catalog, root)
    external = tmp_path / "keep.txt"
    external.write_text("keep")
    record = catalog.template("mapped")
    record["mapping"]["artifacts"] = [str(external)]
    with catalog.db.transaction() as conn:
        conn.execute(
            "UPDATE templates SET mapping_json=? WHERE id='mapped'", (dump(record["mapping"]),)
        )
    service = TemplateLibrary(catalog, root)
    service.delete("mapped")
    with pytest.raises(Problem, match="超出"):
        service.delete("mapped", permanent=True)
    assert external.exists() and source.exists()
