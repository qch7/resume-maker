"""已核对荣誉在既有简历、草稿预览和导出之间的共享内容回归"""

from copy import deepcopy
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from test_resume_previews import register_template
from test_template_mapping import resume_content

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.domain.honor_entries import sync_honor_document
from resume_maker.domain.honors import HonorFields
from resume_maker.domain.resume import ResumeDocument, ResumeSection, SectionEntry
from resume_maker.infrastructure.database import dump
from resume_maker.services.documents import Documents
from resume_maker.services.resume_previews import ResumePreviews


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


def legacy_document(identifier):
    """构造旧版四字段快照和填满的自定义资料"""
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
        document = legacy_document(source["id"])
        payload = {"name": "合成简历", "items": [], "document": document}
        saved = client.post("/api/resumes", json=payload).json()
        # 用临时数据库模拟先前版本保存的条目，读取不写入或迁移用户数据库
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


def test_only_confirmed_matching_sources_update_entries():
    """未核对建议、同名不同来源、手工条目不参与同步，输入对象保持不变"""
    document = legacy_document("linked")
    before = deepcopy(document)
    source = {"id": "linked", "fields": fields(), "reviewed": False}
    assert sync_honor_document(document, [source]) == before
    assert sync_honor_document(document, [{**source, "reviewed": True, "id": "another"}]) == before
    source["reviewed"] = True
    updated = sync_honor_document(document, [source])
    ResumeDocument.model_validate(updated)
    assert updated["personal"] == document["personal"]
    assert document == before
    assert sync_honor_document(updated, [source]) == updated


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

    monkeypatch.setattr("resume_maker.services.resume_previews.render_word", render)
    monkeypatch.setattr("resume_maker.services.documents.render_word", render)
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
                    title="旧证书",
                    hidden_fields=["subtitle", "details"],
                )
            ],
        )
    )
    saved = catalog.save_resume("合成简历", template_id, [], document=document)
    service = ResumePreviews(catalog, data_dir)
    try:
        first = service.render(template_id, document.model_dump(), [])
        assert service.render(template_id, document.model_dump(), []) == first
        history = Documents(catalog, data_dir).export(saved["id"])
        original_manifest = deepcopy(history["manifest"])
        source["fields"]["name"] = "修改后的共享证书"
        source["version"] += 1
        catalog.db.set_setting("honor:linked", source)
        second = service.render(template_id, document.model_dump(), [])
        assert second["id"] != first["id"]
        exported = Documents(catalog, data_dir).export(saved["id"])
        for path in [
            service.file(second["id"], "resume.docx"),
            data_dir / "exports" / exported["id"] / "resume.docx",
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
