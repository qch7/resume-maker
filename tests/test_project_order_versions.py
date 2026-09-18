"""基本信息顺序随版本提交；以及整份草稿二次确认撤销的事务验证"""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_project_info import body_text, project_info
from test_project_order import ORDER, order_template
from test_template_project_slots import project_document

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.domain.experience import replace_field
from resume_maker.domain.models import Experience, ProjectVisibility
from resume_maker.domain.project_layout import project_body_order
from resume_maker.integrations.word.full_resume import write_full_resume
from resume_maker.integrations.word.templates.fill import fill_template


@pytest.mark.parametrize("layout", ["builtin", "body", "row", "details"])
def test_body_order_publishes_new_revision_and_preserves_old_export(
    catalog, project, tmp_path, layout
):
    """调整进入草稿；旧版不变；提交一次产生新版本并覆盖旧简历中的排序设置"""
    identifier, initial = project["id"], project["head_revision"]
    catalog.put_draft(identifier, initial, "experience", project_info(), 0)
    base = catalog.save_revision(identifier, initial, initial)
    original = deepcopy(base["content"])
    meta = {key: value for key, value in original.items() if key != "highlights"}
    working = catalog.put_draft(identifier, base["id"], "meta", {**meta, "body_order": ORDER}, 0)
    assert working["content"]["body_order"] == ORDER
    assert catalog.revision(base["id"])["content"] == original
    count = len(catalog.db.all("SELECT * FROM revisions"))
    saved = catalog.save_revision(identifier, base["id"], base["id"])
    assert saved["number"] == base["number"] + 1
    assert len(catalog.db.all("SELECT * FROM revisions")) == count + 1
    assert saved["content"]["body_order"] == ORDER
    assert saved["content"]["highlights"] == original["highlights"]
    assert not catalog.working(identifier, saved["id"])["drafts"]
    settings = ProjectVisibility(
        order=["stack", "role", "highlights", "description", "custom:link"],
        fields={"role": True, "stack": True},
        custom_fields={"team": True},
    )
    assert project_body_order(saved["content"], settings)[:6] == ORDER
    assert project_body_order(original, settings)[:5] == settings.order
    document = project_document()
    document.project_visibility[identifier] = settings
    output = tmp_path / "result.docx"
    source = tmp_path / "source.docx"
    plan = None if layout == "builtin" else order_template(source, layout)
    for content, expected in [
        (
            saved["content"],
            [
                "example.test",
                "Document processing",
                "Export Word",
                "Parse documents",
                "角色原值",
                "隐藏团队原值",
                "Python",
            ],
        ),
        (
            original,
            [
                "Python",
                "角色原值",
                "Export Word",
                "Parse documents",
                "Document processing",
                "example.test",
            ],
        ),
    ]:
        projects = [{"project_id": identifier, "content": content, "highlight_ids": ["two", "one"]}]
        if plan is None:
            write_full_resume(output, document.model_dump(), projects)
        else:
            fill_template(source, output, plan, document.model_dump(), projects)
        text = body_text(output)
        positions = [text.index(term) for term in expected]
        assert positions == sorted(positions)
    assert (
        replace_field(saved["content"], "experience", {"title": "旧建议", "highlights": []})[
            "body_order"
        ]
        == ORDER
    )


@pytest.mark.parametrize("order", [["title"], ["period"], ["role", "role"], ["custom:"]])
def test_version_order_validated(order):
    """版本和旧布局使用相同合法字段集合；禁止重复及固定顶部字段"""
    with pytest.raises(ValidationError):
        Experience.model_validate({**project_info(), "body_order": order})


def test_atomic_discard_clears_only_confirmed_revision(catalog, project, populated):
    """撤销元信息、排序及亮点增删且不影响其他基线、版本与简历显隐"""
    identifier, revision = project["id"], populated["id"]
    other = project["head_revision"]
    catalog.put_draft(identifier, other, "meta", {"role": "其他基线"}, 0)
    for field, value in [
        ("meta", {"role": "修改角色", "body_order": ORDER}),
        ("order", ["two", "one"]),
        ("highlight:one", None),
        ("highlight:added", {"title": "新增", "text": "内容", "evidence": []}),
    ]:
        catalog.put_draft(identifier, revision, field, value, 0)
    versions = {
        draft["field"]: draft["version"]
        for draft in catalog.working(identifier, revision)["drafts"]
    }
    before = catalog.db.all("SELECT * FROM revisions")
    catalog.discard_drafts(identifier, revision, versions)
    assert catalog.working(identifier, revision) == {"content": populated["content"], "drafts": []}
    assert catalog.working(identifier, other)["content"]["role"] == "其他基线"
    assert catalog.db.all("SELECT * FROM revisions") == before


@pytest.mark.parametrize("concurrent", ["update", "add", "remove"])
def test_discard_conflict_keeps_entire_working_copy(catalog, project, populated, concurrent):
    """确认期间另一窗口新增、修改或删除草稿时；撤销整体失败且不能部分清空"""
    identifier, revision = project["id"], populated["id"]
    catalog.put_draft(identifier, revision, "meta", {"body_order": ORDER}, 0)
    catalog.put_draft(identifier, revision, "order", ["two", "one"], 0)
    versions = {"meta": 1, "order": 1}
    if concurrent == "update":
        catalog.put_draft(identifier, revision, "meta", {"role": "其他窗口"}, 1)
    elif concurrent == "add":
        catalog.put_draft(identifier, revision, "highlight:one", None, 0)
    else:
        catalog.discard_draft(identifier, revision, "order", 1)
    before = catalog.working(identifier, revision)
    with pytest.raises(Problem, match="重新确认"):
        catalog.discard_drafts(identifier, revision, versions)
    assert catalog.working(identifier, revision) == before


def test_discard_api_requires_matching_snapshot(tmp_path):
    """HTTP 撤销需要已确认的草稿版本；冲突时返回 409；成功不产生新版本"""
    app = create_app(Config(data_dir=tmp_path / "data", token="qa"))
    catalog = app.state.services.catalog
    project = catalog.create_project("测试", [str(tmp_path)])
    identifier, revision = project["id"], project["head_revision"]
    catalog.put_draft(identifier, revision, "meta", {"body_order": ORDER}, 0)
    with TestClient(app) as client:
        url = f"/api/projects/{identifier}/drafts/discard"
        assert (
            client.post(
                url,
                json={"base_revision": revision, "versions": {}},
                headers={"x-resume-token": "qa"},
            ).status_code
            == 409
        )
        response = client.post(
            url,
            json={"base_revision": revision, "versions": {"meta": 1}},
            headers={"x-resume-token": "qa"},
        )
        assert response.status_code == 200
        assert response.json()["drafts"] == []
        assert len(catalog.db.all("SELECT * FROM revisions")) == 1
