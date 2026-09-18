"""识别提示与实际资料覆盖一致；混合缺项修复不能遗漏仍未安排的内容"""

import pytest
from test_template_mapping import make_template, project_content, resume_content

from resume_maker.domain.resume import ResumeSection
from resume_maker.domain.templates import TextBinding
from resume_maker.integrations.word.templates.mapping import TemplatePackage
from resume_maker.integrations.word.templates.supplement import supplement_personal_fields
from resume_maker.integrations.word.templates.values import missing_targets
from resume_maker.services.templates.analysis import analysis_context, assess_plan


@pytest.mark.parametrize("visible", [True, False])
def test_project_custom_information_is_requested_and_checked(tmp_path, visible):
    """可见项目自定义信息进入 AI 要求和漏填校验；综合正文能覆盖它且隐藏项不强制输出"""
    package, plan = make_template(tmp_path / "source.docx")
    document, projects = resume_content(), project_content()
    projects[0]["content"]["custom_fields"] = [
        {"id": "link", "label": "项目链接", "value": "https://example.test", "visible": visible}
    ]
    context = analysis_context(package, document, projects)
    assert ("custom_fields" in context["required_entry_fields"]["projects"]) == visible
    assert "https://example.test" not in str(context)
    assert not missing_targets(document, plan, projects)
    region = next(region for region in plan.repeats if region.section == "projects")
    body = next(field for field in region.fields if field.target == "details")
    body.target = "description"
    missing = missing_targets(document, plan, projects)
    assert ("项目经历 · custom_fields" in missing) == visible


def test_personal_fields_are_supplemented_while_other_fields_remain_missing(tmp_path):
    """复现主页、项目自定义项、荣誉名称及时间同时缺位；先补主页且不掩盖其他问题"""
    source = tmp_path / "source.docx"
    package, plan = make_template(source)
    original = source.read_bytes()
    document, projects = resume_content(), project_content()
    document.personal.website = "https://example.test"
    projects[0]["content"]["custom_fields"] = [
        {"id": "link", "label": "项目链接", "value": "https://project.test", "visible": True}
    ]
    region = next(region for region in plan.repeats if region.section == "projects")
    body = next(field for field in region.fields if field.target == "details")
    body.target = "description"
    # 保留项目其他已有绑定；让回归只留下截图中的四项缺位
    for target, quote in (("role", "旧项目正文"), ("stack", "旧第二行")):
        region.fields.append(TextBinding(node=body.node, quote=quote, target=target))
    region.fields.remove(body)
    projects[0]["content"]["description"] = ""
    projects[0]["highlight_ids"] = []
    education = document.sections[0]
    education.title = "荣誉证书"
    education.entries = education.entries[:1]
    education.entries[0].subtitle = ""
    education.entries[0].details = ""
    honor = plan.repeats[0]
    honor.section = "荣誉证书"
    for field in honor.fields:
        if field.target in {"title", "period"}:
            plan.keep.append(field.node)
    honor.fields = [field for field in honor.fields if field.target not in {"title", "period"}]
    assert package.review(plan)["ready"]
    remaining = ["项目经历 · custom_fields", "荣誉证书 · title", "荣誉证书 · period"]
    assert set(missing_targets(document, plan, projects)) == {"personal.website", *remaining}
    snapshot = tmp_path / "snapshot.docx"
    updated, repaired, notices = supplement_personal_fields(
        package, plan, document, projects, snapshot
    )
    assert notices and updated.review(repaired)["ready"]
    assert set(missing_targets(document, repaired, projects)) == set(remaining)
    assert not assess_plan(updated, repaired, document, projects)["ready"]
    assert any(field.target == "personal.website" for field in repaired.fields)
    assert source.read_bytes() == original
    assert TemplatePackage(snapshot).review(repaired)["ready"]
    before = snapshot.read_bytes()
    _, same, notices = supplement_personal_fields(updated, repaired, document, projects, snapshot)
    assert same == repaired and not notices and snapshot.read_bytes() == before


def test_honor_body_does_not_cover_name_or_period(tmp_path):
    """荣誉正文不能代表名称和时间；模型与校验均要求这两项独立映射"""
    package, plan = make_template(tmp_path / "source.docx")
    document = resume_content()
    document.sections[0] = ResumeSection(
        id="honors",
        title="荣誉证书",
        kind="text",
        entries=[{"id": "award", "title": "示例奖项", "period": "2026"}],
    )
    plan.repeats[0].section = "荣誉证书"
    plan.repeats[0].fields = [
        field for field in plan.repeats[0].fields if field.target == "details"
    ]
    context = analysis_context(package, document, [])
    assert context["required_entry_fields"]["荣誉证书"] == ["title", "period"]
    assert missing_targets(document, plan, []) == ["荣誉证书 · title", "荣誉证书 · period"]
