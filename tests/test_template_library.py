"""只有已识别的完整模板可以用于组合、预览、编辑和导出"""

import pytest
from fastapi.testclient import TestClient
from test_resume_previews import register_template
from test_template_analysis import TemplateProvider, completed, simple_document, simple_template
from test_template_mapping import resume_content

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.domain.templates import TemplatePlan
from resume_maker.infrastructure.database import dump, now
from resume_maker.services.documents import Documents
from resume_maker.services.resume_previews import ResumePreviews
from resume_maker.services.workspace import Workspace


def test_only_complete_templates_can_be_selected(catalog, tmp_path):
    """缺少完整映射的记录保留原数据并提示重新识别"""
    data = tmp_path / "data"
    register_template(catalog, data)
    with catalog.db.transaction() as conn:
        conn.execute(
            "INSERT INTO templates VALUES (?,?,?,?,?)",
            ("unavailable", "无完整映射", "unused", dump({}), now()),
        )
    library = Workspace(catalog).state()["templates"]
    assert [item["id"] for item in library] == ["mapped"]
    assert all(set(item) == {"id", "name", "created_at"} for item in library)
    document = resume_content()
    with pytest.raises(Problem, match="AI 识别"):
        catalog.save_resume("缺失映射", "unavailable", [], document=document)
    previews = ResumePreviews(catalog, data)
    with pytest.raises(Problem, match="AI 识别"):
        previews.render("unavailable", document.model_dump(), [])
    resume = catalog.save_resume("完整方案", "mapped", [], document=document)
    with catalog.db.transaction() as conn:
        conn.execute("UPDATE resumes SET template_id='unavailable' WHERE id=?", (resume["id"],))
    with pytest.raises(Problem, match="AI 识别"):
        Documents(catalog, data).export(resume["id"])
    assert catalog.db.one("SELECT mapping_json FROM templates WHERE id='unavailable'") == {
        "mapping": {}
    }
    assert not catalog.db.all("SELECT * FROM exports")
    assert previews.directory is None
    previews.stop()


def test_manual_import_routes_are_removed(tmp_path):
    """模板仅通过完整识别流程导入，旧的段落区间接口不再接受写入"""
    app = create_app(Config(data_dir=tmp_path, token="test"))
    with TestClient(app) as client:
        for route in ("/api/templates", "/api/templates/inspect"):
            response = client.post(route, headers={"x-resume-token": "test"}, json={})
            assert response.status_code == 404
        assert not app.state.services.db.all("SELECT * FROM templates")


def test_saved_recognition_history_survives_restart_and_resave(tmp_path):
    """保存并重启后保留真实活动、轮次、耗时和用量，人工另存不会清空历史或再调用 AI"""

    class RecordedProvider(TemplateProvider):
        """为真实分析流程提供确定的公开活动和统计"""

        def run_structured(self, **kwargs):
            """发出可识别的活动，再沿用脱敏模板的结构化建议"""
            kwargs["emit"]("activity", {"text": "已定位姓名与联系方式 api_key=private"})
            kwargs["emit"](
                "usage", {"input_tokens": 321, "cached_input_tokens": 120, "output_tokens": 65}
            )
            return super().run_structured(**kwargs)

    config = Config(data_dir=tmp_path / "data", token="test")
    source = tmp_path / "source.docx"
    simple_template(source)
    provider = RecordedProvider()
    keys = (
        "events",
        "cursor",
        "round",
        "elapsed_ms",
        "usage",
        "metrics",
        "attempts",
        "repair_error",
        "reused",
        "phase",
    )
    with TestClient(create_app(config, provider)) as client:
        service = client.app.state.services.templates
        task = completed(service, service.analyze(source, simple_document())["id"])
        assert task["events"] and task["round"] > 0
        history = {key: task[key] for key in keys}
        assert history["usage"]["input_tokens"] == 321
        assert "private" not in dump(history)
        saved = service.save(
            task["id"], "保存记录", TemplatePlan.model_validate(task["plan"]), simple_document(), []
        )
        assert saved["mapping"]["analysis"] == history

    restarted_provider = TemplateProvider(failure=True)
    with TestClient(create_app(config, restarted_provider)) as client:
        service = client.app.state.services.templates
        opened = service.open(saved["id"])
        assert opened["from_library"] and opened["status"] == "completed"
        assert opened["id"] != task["id"]
        assert {key: opened[key] for key in keys} == history
        plan = TemplatePlan.model_validate(opened["plan"])
        plan.summary = "已人工核对"
        resaved = service.save(opened["id"], "人工另存", plan, simple_document(), [])
        assert resaved["mapping"]["analysis"] == history
        opened["events"].clear()
        assert service.get(opened["id"])["events"] == history["events"]
        assert not restarted_provider.calls

    with TestClient(create_app(config, restarted_provider)) as client:
        opened = client.post(
            f"/api/templates/{resaved['id']}/edit", headers={"x-resume-token": "test"}
        ).json()
        assert {key: opened[key] for key in keys} == history
        assert opened["plan"]["summary"] == "已人工核对"
