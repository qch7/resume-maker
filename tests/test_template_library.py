"""只有已识别的完整模板可以用于组合、预览、编辑和导出。"""

import pytest
from fastapi.testclient import TestClient
from test_resume_previews import register_template
from test_template_mapping import resume_content

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import dump, now
from resume_maker.services.documents import Documents
from resume_maker.services.resume_previews import ResumePreviews
from resume_maker.services.workspace import Workspace


def test_only_complete_templates_can_be_selected(catalog, tmp_path):
    """缺少完整映射的记录不进入模板库，相关操作提示重新识别，不改写原记录。"""
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
    """模板仅通过完整识别流程导入，旧的段落区间接口不再接受写入。"""
    app = create_app(Config(data_dir=tmp_path, token="test"))
    with TestClient(app) as client:
        for route in ("/api/templates", "/api/templates/inspect"):
            response = client.post(route, headers={"x-resume-token": "test"}, json={})
            assert response.status_code == 404
        assert not app.state.services.db.all("SELECT * FROM templates")
