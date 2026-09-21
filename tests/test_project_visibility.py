"""项目显隐属于简历方案，保存、预览和导出都不创建项目版本"""

import pytest
from test_project_info import body_text, project_info
from test_template_project_slots import metadata_template, project_document

from resume_maker.domain.models import ProjectVisibility, ResumeItem
from resume_maker.infrastructure.database import Database, dump, now
from resume_maker.integrations.sources import digest
from resume_maker.services.catalog import Catalog
from resume_maker.services.documents import Documents
from resume_maker.services.resume_previews import ResumePreviews


@pytest.mark.parametrize("mapped", [False, True])
def test_resume_visibility_isolated_persistent_and_matches_export(
    catalog, project, tmp_path, monkeypatch, mapped
):
    """两份简历可用同一项目版本独立显隐，恢复旧版隐藏项，且预览和正式导出一致"""
    identifier, base = project["id"], project["head_revision"]
    catalog.put_draft(identifier, base, "experience", project_info(), 0)
    revision = catalog.save_revision(identifier, base, base)
    data_dir = tmp_path / "data"
    template_id = None
    if mapped:
        template_id = "mapped"
        source = data_dir / "templates" / template_id / "template.docx"
        source.parent.mkdir(parents=True)
        plan = metadata_template(source, "row", 7)
        with catalog.db.transaction() as conn:
            conn.execute(
                "INSERT INTO templates VALUES (?,?,?,?,?)",
                (
                    template_id,
                    "测试模板",
                    digest(source.read_bytes()),
                    dump({"plan": plan.model_dump()}),
                    now(),
                ),
            )
    document = project_document()
    item = ResumeItem(
        project_id=identifier, revision_id=revision["id"], highlight_ids=["one", "two"]
    )
    original = catalog.save_resume("原简历", template_id, [item], document=document)
    other = catalog.save_resume("另一简历", template_id, [item], document=document)
    before = {
        table: catalog.db.all(f"SELECT * FROM {table}")
        for table in ("revisions", "drafts", "experience_branches")
    }
    document.project_visibility[identifier] = ProjectVisibility(
        fields={"title": False, "period": False, "role": True, "stack": True},
        custom_fields={"link": False, "team": True},
        order=["custom:team", "highlights", "role", "stack", "description"],
    )
    selected = item.model_copy(update={"highlight_ids": ["two"]})
    saved = catalog.save_resume(
        "原简历", template_id, [selected], original["id"], original["version"], document
    )
    reopened = Catalog(Database(catalog.db.path))
    stored = reopened.db.one("SELECT * FROM resumes WHERE id=?", (saved["id"],))
    assert stored["document"]["project_visibility"][identifier]["fields"]["title"] is False
    assert (
        stored["document"]["project_visibility"][identifier]["order"]
        == document.project_visibility[identifier].order
    )
    assert (
        reopened.db.one("SELECT * FROM resumes WHERE id=?", (other["id"],))["document"][
            "project_visibility"
        ]
        == {}
    )
    assert before == {table: catalog.db.all(f"SELECT * FROM {table}") for table in before}
    monkeypatch.setattr(
        "resume_maker.services.documents.render_word", lambda *_: (None, "测试不启动 Word")
    )
    monkeypatch.setattr(
        "resume_maker.services.resume_previews.render_word", lambda *_: (None, "测试不启动 Word")
    )
    previews = ResumePreviews(reopened, data_dir)
    documents = Documents(reopened, data_dir)
    try:
        preview = previews.render(template_id, stored["document"], stored["items"])
        exported = documents.export(saved["id"])
        text = body_text(previews.file(preview["id"], "resume.docx"))
        assert text == body_text(data_dir / "exports" / exported["id"] / "resume.docx")
        assert (
            text.index("隐藏团队原值")
            < text.index("Export Word")
            < text.index("角色原值")
            < text.index("Python")
        )
        assert all(value in text for value in ("角色原值", "Python", "隐藏团队原值", "Export Word"))
        assert all(
            value not in text
            for value in ("项目标题原值", "2025.01", "example.test", "Parse documents")
        )
        unchanged = documents.export(other["id"])
        old_text = body_text(data_dir / "exports" / unchanged["id"] / "resume.docx")
        assert (
            "项目标题原值" in old_text
            and "Parse documents" in old_text
            and "example.test" in old_text
        )
        assert "隐藏团队原值" not in old_text and "角色原值" not in old_text
        assert exported["manifest"]["items"][0]["revision_id"] == revision["id"]
        assert exported["manifest"]["items"][0]["content"] == revision["content"]
        assert before == {table: catalog.db.all(f"SELECT * FROM {table}") for table in before}
    finally:
        previews.stop()
