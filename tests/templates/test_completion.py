"""不同模板容器和任意栏目名共用补位流程，检查、保存及输出不会相互矛盾"""

import base64
import threading
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.domain.models import ProjectVisibility, ProviderSettings
from resume_maker.infrastructure.database import dump, now
from resume_maker.integrations.sources import digest
from resume_maker.integrations.word.templates.completion import complete_template
from resume_maker.integrations.word.templates.fill import fill_template
from resume_maker.integrations.word.templates.mapping import TemplatePackage
from resume_maker.integrations.word.templates.values import missing_targets
from resume_maker.plugin_packages.ext_template_ai.services.templates.analysis import (
    analyze_plan,
    assess_plan,
)
from resume_maker.plugin_packages.ext_template_ai.services.templates.cache import (
    cache_path,
    cached_plan,
    remember_plan,
)
from resume_maker.plugin_packages.sys_resume.services.resumes import Resumes
from tests.support.document_services import use_renderer
from tests.support.documents import photo_bytes
from tests.support.layouts import generic_content, generic_template, visible_text
from tests.support.templates import TemplateProvider, completed


@pytest.mark.parametrize("layout", ["body", "rows", "cells"])
@pytest.mark.parametrize("padding", [0, 11])
def test_mixed_fields_complete_in_unrelated_layouts(tmp_path, layout, padding):
    """不同节点编号和容器均补齐混合缺项，反复运行不增行，显隐变化不泄露资料"""
    source, snapshot, output = [
        tmp_path / name for name in ("source.docx", "snapshot.docx", "output.docx")
    ]
    package, plan = generic_template(source, layout, padding)
    original, original_plan = source.read_bytes(), deepcopy(plan)
    document, projects = generic_content()
    assert set(missing_targets(document, plan, projects)) == {
        "personal.website",
        "Portfolio Ω · custom_fields",
        "Recognition · β · title",
        "Recognition · β · period",
        "Recognition · β · custom_fields",
    }
    repaired, mapping, notices = complete_template(package, plan, document, projects, snapshot)
    assert notices and assess_plan(repaired, mapping, document, projects)["ready"]
    assert any("Portfolio Ω" in notice for notice in notices)
    assert not any("projects" in notice for notice in notices)
    assert TemplatePackage(snapshot).review(mapping)["ready"]
    before = snapshot.read_bytes()
    _, same, notices = complete_template(repaired, mapping, document, projects, snapshot)
    assert same == mapping and not notices and before == snapshot.read_bytes()
    fill_template(snapshot, output, mapping, document.model_dump(), projects)
    text = visible_text(output)
    assert text.count(document.personal.website) == 1
    for index in range(2):
        for literal in (
            f"Project {index}",
            f"Repository：https://repo{index}.example.test",
            f"Award {index}",
            f"Date {index}",
            f"Entry body {index}",
            f"Issuer：Institute {index}",
        ):
            assert text.count(literal) == 1
    assert "Old " not in text and "〔" not in text and text.endswith("Fixed ending")
    document.personal.hidden_fields = ["website"]
    document.sections[1].entries[0].hidden_fields = ["period"]
    document.project_visibility = {"project-0": ProjectVisibility(custom_fields={"link": False})}
    fill_template(snapshot, output, mapping, document.model_dump(), projects)
    text = visible_text(output)
    assert "profile.example.test" not in text and "repo0.example.test" not in text
    assert "Date 0" not in text and "Date 1" in text and "repo1.example.test" in text
    assert source.read_bytes() == original and plan == original_plan


def test_missing_photo_and_unknown_original_content_still_block(tmp_path):
    """可补位字段不会掩盖未识别照片或原文，无法完成时仍阻止丢失信息的输出"""
    source = tmp_path / "source.docx"
    package, plan = generic_template(source)
    document, projects = generic_content()
    document.personal.photo = "data:image/png;base64," + base64.b64encode(photo_bytes(50)).decode()
    repaired, mapping, _ = complete_template(package, plan, document, projects)
    assert missing_targets(document, mapping, projects) == ["照片"]
    assert not assess_plan(repaired, mapping, document, projects)["ready"]
    with pytest.raises(Problem, match="照片"):
        fill_template(source, tmp_path / "output.docx", plan, document.model_dump(), projects)
    plan.fields = [field for field in plan.fields if field.target != "personal.name"]
    unchanged, same, notices = complete_template(package, plan, document, projects)
    assert unchanged is package and same == plan and not notices
    assert not unchanged.review(same)["ready"]


def test_cache_cannot_hide_new_field_requirements(tmp_path):
    """相同字段的新值可复用缓存，新增可见字段会失效，旧缓存不能掩盖新增内容"""
    package, plan = generic_template(tmp_path / "source.docx")
    document, projects = generic_content()
    document.personal.website = ""
    for entry in document.sections[1].entries:
        entry.title = entry.period = ""
        entry.custom_fields = []
    for project in projects:
        project["content"]["custom_fields"] = []
    settings = ProviderSettings()
    original_path = cache_path(tmp_path, package, document, projects, settings)
    remember_plan(original_path, plan)
    assert cached_plan(original_path, package, document, projects) is not None
    document.personal.name = "Another Person"
    assert cache_path(tmp_path, package, document, projects, settings) == original_path
    document.personal.website = "https://new.example.test"
    assert cache_path(tmp_path, package, document, projects, settings) != original_path
    assert cached_plan(original_path, package, document, projects) is None
    document.personal.hidden_fields = ["website"]
    assert cache_path(tmp_path, package, document, projects, settings) == original_path
    assert cached_plan(original_path, package, document, projects) is not None


def test_renamed_project_heading_can_supply_new_section_style(tmp_path):
    """项目栏目改名后仍可复用大标题样式"""
    source = tmp_path / "source.docx"
    package, plan = generic_template(source)
    # 移除普通栏目示例且只保留一个以任意名称命名的项目栏目
    ordinary = plan.repeats.pop()
    heading = next(field for field in plan.fields if field.target.endswith("Recognition · β"))
    plan.fields.remove(heading)
    plan.remove.extend([heading.node, ordinary.start])
    document, projects = generic_content()
    repaired, mapping, _ = complete_template(package, plan, document, projects)
    assert assess_plan(repaired, mapping, document, projects)["ready"]
    snapshot = tmp_path / "snapshot.docx"
    repaired.write(snapshot)
    output = tmp_path / "output.docx"
    fill_template(snapshot, output, mapping, document.model_dump(), projects)
    text = visible_text(output)
    assert text.count("Recognition · β") == 1 and "Award 0" in text


def test_first_analysis_completes_all_supported_missing_fields(tmp_path, monkeypatch):
    """首轮识别完整原文后即补齐混合缺项，最终清单、源快照和方案使用同一套编号"""
    source = tmp_path / "original.docx"
    package, plan = generic_template(source, "cells", 8)
    document, projects = generic_content()
    monkeypatch.setattr(
        "resume_maker.plugin_packages.ext_template_ai.services.templates.analysis.source_pages",
        lambda *_: ([], {}, []),
    )

    class MappedProvider(TemplateProvider):
        """只识别已有原文，缺少的位置必须由通用补位器处理"""

        def run_structured(self, **kwargs):
            """返回预先核对的模板映射"""
            self.calls.append(kwargs)
            return plan.model_copy(deep=True)

    def emit(*_):
        """测试忽略公开进度且只核验结果和实际文件"""

    provider = MappedProvider()
    mapping, review, attempts, error = analyze_plan(
        package, provider, tmp_path, document, projects, ProviderSettings(), threading.Event(), emit
    )
    assert review["ready"] and not review["missing"] and attempts == 1 and error is None
    assert len(provider.calls) == 1 and TemplatePackage(source).review(mapping)["ready"]
    output = tmp_path / "output.docx"
    fill_template(source, output, mapping, document.model_dump(), projects)
    assert "Award 1" in visible_text(
        output
    ) and "Repository：https://repo0.example.test" in visible_text(output)


def test_library_review_save_and_reopen_share_completion(tmp_path, monkeypatch):
    """真实接口打开旧模板、资料新增后的检查、试填及保存均补齐，原版本和任务源文件不变"""
    config = Config(data_dir=tmp_path / "data", token="test")
    provider = TemplateProvider(failure=True)
    app = create_app(config, provider)
    use_renderer(app, monkeypatch, lambda *_: (None, "测试无渲染器"))
    with TestClient(app) as client:
        catalog = app.state.services.catalog
        folder = config.data_dir / "templates" / "generic"
        folder.mkdir(parents=True)
        _, plan = generic_template(folder / "template.docx", "rows", 5)
        original = (folder / "template.docx").read_bytes()
        staged = catalog.assets.stage_bundle("ext.template-adapter", {"template.docx": original})
        with catalog.db.transaction() as conn:
            catalog.assets.publish_bundle(conn, "ext.template-adapter", "templates/generic", staged)
            conn.execute(
                "INSERT INTO templates VALUES (?,?,?,?,?)",
                ("generic", "任意模板", digest(original), dump({"plan": plan.model_dump()}), now()),
            )
        document, projects = generic_content()
        items = []
        for data in projects:
            project_root = tmp_path / data["project_id"]
            project_root.mkdir()
            project = catalog.create_project(data["project_id"], [str(project_root)])
            base = project["head_revision"]
            catalog.put_draft(project["id"], base, "experience", data["content"], 0)
            revision = catalog.save_revision(project["id"], base, base)
            items.append(
                {"project_id": project["id"], "revision_id": revision["id"], "highlight_ids": []}
            )
        headers = {"x-resume-token": "test"}
        body = {"document": document.model_dump(), "items": items}
        legacy = client.post("/api/templates/generic/edit", headers=headers).json()
        repair = client.post(
            f"/api/templates/analyses/{legacy['id']}/repair",
            json={**body, "plan": legacy["plan"]},
            headers=headers,
        )
        assert repair.status_code == 200
        repaired = completed(app.state.services.templates, repair.json()["id"])
        assert repaired["review"]["ready"] and repaired["attempts"] == 0
        assert not provider.calls
        response = client.post("/api/templates/generic/edit", json=body, headers=headers)
        assert response.status_code == 200
        opened = response.json()
        assert opened["review"]["ready"] and not opened["review"]["missing"]
        assert not provider.calls
        task_source = app.state.services.templates.source(opened["id"])
        assert opened["inventory"]["nodes"] == TemplatePackage(task_source).inventory()["nodes"]
        # 打开后继续新增字段，检查和保存必须和预览使用相同的自动补位规则
        body["document"]["personal"]["phone"] = "123456789"
        body["document"]["sections"][1]["entries"][0]["subtitle"] = "New subtitle"
        body["plan"] = opened["plan"]
        task_bytes = task_source.read_bytes()
        prefix = f"/api/templates/analyses/{opened['id']}"
        reviewed = client.post(prefix + "/review", json=body, headers=headers).json()
        assert reviewed["ready"] and reviewed["missing"] == [] and reviewed["notices"]
        preview = client.post(prefix + "/preview", json=body, headers=headers)
        assert preview.status_code == 200
        assert preview.json()["pages"] is None
        with app.state.services.templates.preview_lease(
            opened["id"], preview.json()["id"], "resume.docx"
        ) as output:
            assert "电话：123456789" in visible_text(output) and "New subtitle" in visible_text(
                output
            )
        saved = client.post(prefix + "/save", json={**body, "name": "新版"}, headers=headers)
        assert saved.status_code == 200
        reopened = client.post(
            f"/api/templates/{saved.json()['id']}/edit",
            json={"document": body["document"], "items": items},
            headers=headers,
        )
        assert reopened.status_code == 200 and reopened.json()["review"]["ready"]
        assert (
            folder / "template.docx"
        ).read_bytes() == original and task_source.read_bytes() == task_bytes
        assert (
            Resumes(catalog, storage=catalog.db, assets=catalog.assets).template("generic")[
                "mapping"
            ]["plan"]
            == plan.model_dump()
        )
