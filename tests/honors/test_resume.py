"""荣誉快照、关联同步、简历输出"""

import json
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from lxml import etree

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.domain.honors import HonorFields, HonorSave
from resume_maker.domain.resume import ResumeDocument, ResumeSection, SectionEntry
from resume_maker.infrastructure.assets import Assets
from resume_maker.infrastructure.database import dump
from resume_maker.integrations.word.full_resume import write_full_resume
from resume_maker.integrations.word.ooxml import NS
from resume_maker.integrations.word.templates.values import section_records
from resume_maker.plugin_packages.ext_honors.services.honor_links import resume_source
from resume_maker.plugin_packages.ext_honors.services.honors import Honors
from resume_maker.plugin_packages.sys_resume.services.resume_sources import ResumeSources
from resume_maker.plugin_packages.sys_resume.services.resumes import Resumes
from resume_maker.runtime.host import Contribution
from tests.support.document_services import Documents, ResumePreviews
from tests.support.documents import resume_content
from tests.support.templates import register_template


def honor_registry(db):
    """独立业务验收沿用生产环境的来源贡献"""
    contribution = Contribution(
        "ext.honors", "resume.sources", "ext.honors/library", resume_source()
    )
    return ResumeSources(db, lambda point: [contribution])


def test_honor_snapshot_roundtrip_and_rendering(catalog, tmp_path, fixtures_dir):
    """前端生成的完整字段副本保存无损，内置、模板填充默认仅使用名称及日期"""
    fixture = fixtures_dir / "honor-entry.json"
    entry = json.loads(fixture.read_text(encoding="utf-8"))
    document = ResumeDocument.model_validate(
        {
            "sections": [
                {"id": "projects", "title": "项目经历", "kind": "projects"},
                {"id": "honors", "title": "资格与成果", "entries": [entry]},
            ]
        }
    )
    saved = Resumes(
        catalog,
        sources=honor_registry(catalog.db),
        storage=catalog.db,
        assets=catalog.assets,
    ).save_resume("荣誉测试", None, [], document=document)
    restored = ResumeDocument.model_validate(saved["document"])
    stored = restored.sections[1].entries[0]
    assert stored.field_definitions is None
    assert stored.model_dump(exclude={"field_definitions"}) == entry
    records = section_records(restored, "资格与成果", [])
    assert len(records) == 1
    assert records[0]["title"] == entry["title"]
    assert records[0]["period"] == entry["period"]
    assert not any(records[0][key] for key in ("subtitle", "details", "custom_fields"))

    output = tmp_path / "honors.docx"
    write_full_resume(output, restored.model_dump(), [])
    text = word_text(output)
    assert entry["title"] in text and entry["period"] in text
    assert entry["subtitle"] not in text and "示例获奖项目" not in text
    for field in entry["custom_fields"]:
        assert field["value"] not in text

    stored.hidden_fields.remove("subtitle")
    stored.custom_fields[0].visible = True
    write_full_resume(output, restored.model_dump(), [])
    text = word_text(output)
    assert entry["subtitle"] in text
    assert "奖项：一等奖" in text
    assert "示例获奖项目" not in text
    records = section_records(restored, "资格与成果", [])
    assert records[0]["subtitle"] == entry["subtitle"]
    assert records[0]["custom_fields"] == "奖项：一等奖"
    assert records[0]["details"] == ""
    assert saved["document"]["sections"][1]["entries"][0] == {
        **entry,
        "field_definitions": None,
    }


def word_text(path):
    """读取真实生成 DOCX 的可见文本以检查排版采用的资料"""
    with ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    return "".join(root.xpath("//w:t/text()", namespaces=NS))


def fields(name="同步后的证书"):
    """生成九个字段均完整的合成荣誉资料"""
    return HonorFields(
        name=name,
        date="2026-09",
        issuer="同步单位",
        award="一等奖",
        level="省级",
        category="竞赛获奖",
        recipient="同步团队",
        certificate_number="DEMO-003",
        description="单独的获奖项目说明",
    ).model_dump()


def linked_document(identifier):
    """构造明确关联来源的过时快照、填满的自定义资料"""
    return ResumeDocument.model_validate(
        {
            "personal": {"name": "姓名草稿"},
            "sections": [
                {"id": "projects", "title": "项目经历", "kind": "projects"},
                {
                    "id": "honors",
                    "title": "改名后的成果",
                    "entries": [
                        {
                            "id": f"honor:{identifier}",
                            "source": {
                                "provider": "ext.honors/library",
                                "id": identifier,
                                "version": "1",
                            },
                            "title": "旧名称 · 一等奖",
                            "subtitle": "旧单位",
                            "period": "旧日期",
                            "details": "省级\n旧说明",
                            "hidden_fields": ["subtitle", "details"],
                            "visible": False,
                            "custom_fields": [
                                {
                                    "id": f"note-{index}",
                                    "label": "备注",
                                    "value": str(index),
                                    "visible": False,
                                }
                                for index in range(20)
                            ],
                        }
                    ],
                },
            ],
        }
    ).model_dump()


def test_existing_linked_honors_sync_on_read_save_and_delete(tmp_path):
    """已有缺字段条目自动补全，过时简历保存不能倒写来源，删除保留最后核对内容"""
    app = create_app(Config(data_dir=tmp_path, token="test"))
    with TestClient(app, headers={"x-resume-token": "test"}) as client:
        source = client.post("/api/honors", json={"fields": fields()}).json()
        document = linked_document(source["id"])
        payload = {"name": "合成简历", "items": [], "document": document}
        saved = client.post("/api/resumes", json=payload).json()
        # 用临时数据库模拟来源修改前的确认快照，读取不修改持久版本
        with app.state.services.db.transaction() as conn:
            conn.execute(
                "UPDATE resumes SET document_json=? WHERE id=?", (dump(document), saved["id"])
            )
        state = client.get("/api/state").json()
        entry = state["resumes"][0]["document"]["sections"][1]["entries"][0]
        assert set(state["honors"][0]) == {"id", "fields", "reviewed", "version", "updated_at"}
        assert state["honors"][0]["updated_at"] == source["updated_at"]
        assert entry["title"] == fields()["name"]
        assert entry["details"] == fields()["description"]
        assert entry["custom_fields"][:20] == document["sections"][1]["entries"][0]["custom_fields"]
        assert len(entry["custom_fields"]) == 25
        assert entry["hidden_fields"] == ["subtitle", "details"]
        assert not entry["visible"]
        assert state["resumes"][0]["version"] == saved["version"]
        assert (
            app.state.services.db.one("SELECT * FROM resumes WHERE id=?", (saved["id"],))[
                "document"
            ]
            == document
        )

        changed = {**fields("再次更新证书"), "award": "", "description": ""}
        response = client.put(
            f"/api/honors/{source['id']}", json={"fields": changed, "version": source["version"]}
        )
        assert response.status_code == 200
        latest = response.json()
        response = client.put(
            f"/api/resumes/{saved['id']}", json={**payload, "version": saved["version"]}
        )
        assert response.status_code == 200, response.text
        current = response.json()["document"]["sections"][1]["entries"][0]
        assert current["title"] == changed["name"] and current["details"] == ""
        assert (
            next(item for item in current["custom_fields"] if item["id"] == "honor-field:award")[
                "value"
            ]
            == ""
        )
        assert client.get("/api/honors").json()[0]["fields"] == changed
        assert (
            client.put(
                f"/api/honors/{source['id']}",
                json={"fields": fields(), "version": source["version"]},
            ).status_code
            == 409
        )

        final = {**changed, "name": "删除前最后资料"}
        latest = client.put(
            f"/api/honors/{source['id']}", json={"fields": final, "version": latest["version"]}
        ).json()
        assert (
            client.delete(f"/api/honors/{source['id']}?version={latest['version']}").status_code
            == 200
        )
        state = client.get("/api/state").json()
        assert state["honors"] == []
        assert (
            state["resumes"][0]["document"]["sections"][1]["entries"][0]["title"] == final["name"]
        )


def test_only_confirmed_matching_sources_update_entries(catalog):
    """未核对建议、同名不同来源、手工条目不参与同步，输入对象保持不变"""
    document = linked_document("linked")
    before = deepcopy(document)
    source = {"id": "linked", "fields": fields(), "reviewed": False, "version": 1}
    registry = honor_registry(catalog.db)
    catalog.db.set_setting("honor:linked", source)
    assert registry.resolve(document) == before
    catalog.db.set_setting("honor:another", {**source, "reviewed": True, "id": "another"})
    assert registry.resolve(document) == before
    source["reviewed"] = True
    catalog.db.set_setting("honor:linked", source)
    updated = registry.resolve(document)
    ResumeDocument.model_validate(updated)
    assert updated["personal"] == document["personal"]
    assert document == before
    assert registry.resolve(updated) == updated


def store_resume_snapshots(db, documents):
    """登记来源更新前的合成快照，性能统计只覆盖随后读取或保留阶段"""
    with db.transaction() as conn:
        conn.executemany(
            "INSERT INTO resumes "
            "(id,name,template_id,items_json,version,created_at,updated_at,document_json) "
            "VALUES (?, ?, NULL, '[]', 1, '2026-10-14', '2026-10-14', ?)",
            [
                (f"resume-{index}", f"合成简历{index}", dump(doc))
                for index, doc in enumerate(documents)
            ],
        )


def test_workspace_batches_shared_honors_across_fifty_resumes(catalog):
    """五十份简历共用二十条荣誉时仅查询简历、荣誉各一次，读取不改持久快照"""
    documents = []
    for number in range(50):
        document = linked_document("honor-0")
        seed = document["sections"][1]["entries"][0]
        seed["custom_fields"] = [{"id": "note", "label": "备注", "value": str(number)}]
        entries = []
        for index in range(20):
            entry = deepcopy(seed)
            entry["id"] = f"entry-{index}"
            entry["source"]["id"] = f"honor-{index}"
            entries.append(entry)
        document["sections"][1]["entries"] = entries
        documents.append(document)
    store_resume_snapshots(catalog.db, documents)
    with catalog.db.transaction() as conn:
        conn.executemany(
            "INSERT INTO settings VALUES (?,?)",
            [
                (
                    f"honor:honor-{index}",
                    dump(
                        {
                            "id": f"honor-{index}",
                            "fields": fields(f"当前荣誉{index}"),
                            "reviewed": True,
                            "version": 2,
                        }
                    ),
                )
                for index in range(20)
            ],
        )
    service = Resumes(
        catalog, storage=catalog.db, assets=catalog.assets, sources=honor_registry(catalog.db)
    )
    statements = []
    with catalog.db.connect() as conn:
        conn.execute("BEGIN")
        conn.set_trace_callback(statements.append)
        state = service.workspace_state(conn)
        conn.set_trace_callback(None)
    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 2
    assert len(state["resumes"]) == 50
    for resume in state["resumes"]:
        entries = resume["document"]["sections"][1]["entries"]
        assert [entry["title"] for entry in entries] == [f"当前荣誉{index}" for index in range(20)]
        assert all(entry["source"]["version"] == "2" for entry in entries)
        assert all(entry["visible"] is False for entry in entries)
        assert resume["version"] == 1
    first = state["resumes"][0]["document"]["sections"][1]["entries"][0]
    first["custom_fields"][-1]["value"] = "仅修改当前结果"
    assert (
        state["resumes"][1]["document"]["sections"][1]["entries"][0]["custom_fields"][-1]["value"]
        != "仅修改当前结果"
    )
    assert catalog.db.one("SELECT * FROM resumes WHERE id='resume-0'")["document"] == documents[0]


@pytest.mark.parametrize("count", [0, 501, 1001])
def test_honor_source_resolves_large_batches_and_keeps_requested_order(catalog, count):
    """超过单批参数上限时分块查询，重复、缺失及未复核条目不污染返回顺序"""
    identifiers = [f"honor-{index:04}" for index in range(count)]
    with catalog.db.transaction() as conn:
        conn.executemany(
            "INSERT INTO settings VALUES (?,?)",
            [
                (
                    f"honor:{identifier}",
                    dump(
                        {
                            "id": identifier,
                            "fields": fields(identifier),
                            "reviewed": index != 1,
                            "version": 2,
                        }
                    ),
                )
                for index, identifier in enumerate(identifiers)
                if index != 2
            ],
        )
        requested = list(reversed(identifiers))
        requested += requested[:3]
        statements = []
        conn.set_trace_callback(statements.append)
        reader = catalog.db.read_session(conn)
        try:
            result = resume_source().resolve(reader, tuple(requested))
        finally:
            reader.close()
            conn.set_trace_callback(None)
    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    assert len(selects) == (count + 499) // 500
    assert [item.id for item in result] == [
        identifier for identifier in reversed(identifiers) if identifier not in identifiers[1:3]
    ]
    assert all(item.version == "2" for item in result)


def test_preserve_many_honor_snapshots_uses_callers_transaction(catalog):
    """保留多个快照读取未提交荣誉，异常时整批回滚，删除后仍留下最后确认资料"""
    original = {"id": "linked", "fields": fields("初始资料"), "reviewed": True, "version": 1}
    catalog.db.set_setting("honor:linked", original)
    documents = [linked_document("linked"), linked_document("linked"), linked_document("missing")]
    store_resume_snapshots(catalog.db, documents)
    service = Resumes(
        catalog, storage=catalog.db, assets=catalog.assets, sources=honor_registry(catalog.db)
    )
    current = {**original, "fields": fields("事务内最新资料"), "version": 2}
    with pytest.raises(RuntimeError, match="回滚"):
        with catalog.db.transaction() as conn:
            conn.execute(
                "UPDATE settings SET value_json=? WHERE key='honor:linked'", (dump(current),)
            )
            service.preserve_sources(conn)
            saved = json.loads(
                conn.execute("SELECT document_json FROM resumes WHERE id='resume-0'").fetchone()[0]
            )
            assert saved["sections"][1]["entries"][0]["title"] == "事务内最新资料"
            raise RuntimeError("回滚")
    assert catalog.db.setting("honor:linked") == original
    assert catalog.db.one("SELECT * FROM resumes WHERE id='resume-0'")["document"] == documents[0]
    assert catalog.db.one("SELECT * FROM resumes WHERE id='resume-1'")["version"] == 1
    with catalog.db.transaction() as conn:
        conn.execute("UPDATE settings SET value_json=? WHERE key='honor:linked'", (dump(current),))
        service.preserve_sources(conn)
        conn.execute("DELETE FROM settings WHERE key='honor:linked'")
    for index in range(2):
        saved = catalog.db.one("SELECT * FROM resumes WHERE id=?", (f"resume-{index}",))
        assert saved["version"] == 2
        assert saved["document"]["sections"][1]["entries"][0]["title"] == "事务内最新资料"
    missing = catalog.db.one("SELECT * FROM resumes WHERE id='resume-2'")
    assert missing["version"] == 1 and missing["document"] == documents[2]
    with pytest.raises(Problem, match="其他窗口"):
        service.save_resume(
            "过时修改", None, [], "resume-0", 1, ResumeDocument.model_validate(documents[0])
        )


@pytest.mark.parametrize("template_id", [None, "mapped"])
def test_preview_and_export_resolve_current_honors_and_invalidate_cache(
    catalog, tmp_path, monkeypatch, template_id
):
    """旧草稿也生成当前荣誉，新核对内容使预览缓存失效且旧导出清单保持原样"""

    def render(source, output):
        """只代替分页软件，真实 DOCX 填充、内容检查仍完整执行"""
        output.write_bytes(b"pdf")
        (output.parent / "page-1.png").write_bytes(b"png")
        return 1, None

    monkeypatch.setattr("tests.support.document_services.render_word", render)
    monkeypatch.setattr("tests.support.document_services.render_word", render)
    data_dir = tmp_path / "data"
    register_template(catalog, data_dir)
    source = {"id": "linked", "fields": fields(), "reviewed": True, "version": 1}
    catalog.db.set_setting("honor:linked", source)
    document = resume_content()
    document.sections.append(
        ResumeSection(
            id="honors",
            title="荣誉证书",
            entries=[
                SectionEntry(
                    id="honor:linked",
                    source={"provider": "ext.honors/library", "id": "linked", "version": "1"},
                    title="旧证书",
                    hidden_fields=["subtitle", "details"],
                )
            ],
        )
    )
    saved = Resumes(
        catalog,
        sources=honor_registry(catalog.db),
        storage=catalog.db,
        assets=catalog.assets,
    ).save_resume("合成简历", template_id, [], document=document)
    service = ResumePreviews(
        Resumes(
            catalog,
            sources=honor_registry(catalog.db),
            storage=catalog.db,
            assets=catalog.assets,
        ),
        data_dir,
    )
    try:
        first = service.render(template_id, document.model_dump(), [])
        assert service.render(template_id, document.model_dump(), []) == first
        history = Documents(
            Resumes(
                catalog,
                sources=honor_registry(catalog.db),
                storage=catalog.db,
                assets=catalog.assets,
            ),
            data_dir,
            storage=catalog.db,
            assets=Assets(catalog.db, data_dir),
        ).export(saved["id"])
        original_manifest = deepcopy(history["manifest"])
        source["fields"]["name"] = "修改后的共享证书"
        source["version"] += 1
        catalog.db.set_setting("honor:linked", source)
        second = service.render(template_id, document.model_dump(), [])
        assert second["id"] != first["id"]
        exported = Documents(
            Resumes(
                catalog,
                sources=honor_registry(catalog.db),
                storage=catalog.db,
                assets=catalog.assets,
            ),
            data_dir,
            storage=catalog.db,
            assets=Assets(catalog.db, data_dir),
        ).export(saved["id"])
        for path in [
            service.file(second["id"], "resume.docx"),
            BytesIO(catalog.assets.read_file(f"exports/{exported['id']}", "resume.docx")),
        ]:
            with ZipFile(path) as archive:
                xml = archive.read("word/document.xml").decode()
            assert "修改后的共享证书" in xml and "2026-09" in xml
            assert "旧证书" not in xml and "同步单位" not in xml and "单独的获奖项目说明" not in xml
        assert (
            catalog.db.one("SELECT * FROM exports WHERE id=?", (history["id"],))["manifest"]
            == original_manifest
        )
    finally:
        service.stop()


def test_save_reports_exact_saved_resume_links_without_publishing_drafts(catalog, tmp_path):
    """保存响应统计实际来源关联，重复引用、其他提供方、删除方案不虚增数量"""
    resumes = Resumes(catalog, storage=catalog.db, assets=catalog.assets)
    honors = Honors(
        catalog.db, tmp_path, None, assets=catalog.assets, source_usage=resumes.source_usage
    )
    source = honors.save(HonorSave(fields=HonorFields(name="合成证书")))
    assert source["linked_resume_count"] == 0
    document = linked_document(source["id"])
    duplicate = deepcopy(document["sections"][1]["entries"][0])
    duplicate["id"] = "duplicate-reference"
    document["sections"][1]["entries"].append(duplicate)
    first = resumes.save_resume(
        "方案一", None, [], document=ResumeDocument.model_validate(document)
    )
    second = resumes.save_resume(
        "方案二", None, [], document=ResumeDocument.model_validate(document)
    )
    other = deepcopy(document)
    for entry in other["sections"][1]["entries"]:
        entry["source"]["provider"] = "community.other/library"
    resumes.save_resume("不同来源", None, [], document=ResumeDocument.model_validate(other))
    updated = honors.save(
        HonorSave(fields=HonorFields(name="核对后的证书"), version=source["version"]), source["id"]
    )
    assert updated["linked_resume_count"] == 2
    assert "linked_resume_count" not in honors.get(source["id"])
    assert catalog.db.one("SELECT version FROM resumes WHERE id=?", (first["id"],))["version"] == 1
    resumes.delete_resume(second["id"], second["version"])
    updated = honors.save(
        HonorSave(fields=HonorFields(name="再次核对"), version=updated["version"]), source["id"]
    )
    assert updated["linked_resume_count"] == 1
    with catalog.db.transaction() as conn:
        conn.execute("DELETE FROM resumes WHERE id=?", (first["id"],))
        assert resumes.source_usage(conn, "ext.honors/library", source["id"]) == 0
