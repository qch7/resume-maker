"""荣誉快照、关联同步和简历输出"""

import json
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from lxml import etree

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.domain.honors import HonorFields
from resume_maker.domain.resume import ResumeDocument, ResumeSection, SectionEntry
from resume_maker.infrastructure.assets import Assets
from resume_maker.infrastructure.database import dump
from resume_maker.integrations.word.full_resume import write_full_resume
from resume_maker.integrations.word.ooxml import NS
from resume_maker.integrations.word.templates.values import section_records
from resume_maker.plugin_packages.ext_honors.services.honor_links import resume_source
from resume_maker.plugin_packages.sys_resume.services.resume_sources import ResumeSources
from resume_maker.plugin_packages.sys_resume.services.resumes import Resumes
from resume_maker.runtime.host import Contribution
from tests.support.document_services import Documents, ResumePreviews
from tests.support.documents import resume_content
from tests.support.templates import register_template


def honor_registry(db):
    """独立业务验收使用和生产相同的来源贡献"""
    contribution = Contribution(
        "ext.honors", "resume.sources", "ext.honors/library", resume_source()
    )
    return ResumeSources(db, lambda point: [contribution])


def test_honor_snapshot_roundtrip_and_rendering(catalog, tmp_path, fixtures_dir):
    """前端生成的完整字段副本保存无损，内置和模板填充默认仅使用名称及日期"""
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
    """构造明确关联来源的过时快照和填满的自定义资料"""
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


@pytest.mark.parametrize("template_id", [None, "mapped"])
def test_preview_and_export_resolve_current_honors_and_invalidate_cache(
    catalog, tmp_path, monkeypatch, template_id
):
    """旧草稿也生成当前荣誉，新核对内容使预览缓存失效且旧导出清单保持原样"""

    def render(source, output):
        """只代替分页软件，真实 DOCX 填充和内容检查仍完整执行"""
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
