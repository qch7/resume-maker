"""验证不同模板的补全规则及格式失败时的有限重试"""

import json
import threading
from copy import deepcopy

import pytest
from lxml import etree
from test_template_analysis import TemplateProvider, simple_document, simple_template
from test_template_completion import generic_content, generic_template, visible_text

from resume_maker.domain.models import ProviderSettings
from resume_maker.domain.resume import ResumeSection
from resume_maker.integrations.providers.base import Cancelled, StructuredOutputError
from resume_maker.integrations.word.ooxml import w
from resume_maker.integrations.word.templates.fill import fill_template
from resume_maker.integrations.word.templates.mapping import TemplatePackage
from resume_maker.integrations.word.templates.supplement import remap_plan
from resume_maker.services.templates.analysis import analyze_plan


@pytest.mark.parametrize("layout", ["body", "rows", "cells"])
def test_project_title_alias_uses_actual_name_and_visibility(tmp_path, layout):
    """项目区和标题共用别名时按实际栏目处理改名和显隐"""
    source, output = tmp_path / "source.docx", tmp_path / "result.docx"
    _, plan = generic_template(source, layout)
    document, projects = generic_content()
    project = next(section for section in document.sections if section.kind == "projects")
    field = next(field for field in plan.fields if field.target == "section-title:" + project.title)
    field.target = "section-title:projects"
    original = plan.model_dump()
    project.title = "Renamed research work"
    fill_template(source, output, plan, document.model_dump(), projects)
    assert visible_text(output).count(project.title) == 1
    project.visible = False
    fill_template(source, output, plan, document.model_dump(), projects)
    assert project.title not in visible_text(output)
    assert plan.model_dump() == original


@pytest.mark.parametrize("layout", ["body", "rows", "cells"])
@pytest.mark.parametrize("variant", range(4))
def test_mapping_survives_run_fragmentation_renaming_and_record_changes(tmp_path, layout, variant):
    """节点重新编号、非默认栏目名及不同数量的真实记录都不能改变填充完整性"""
    source, output = tmp_path / "source.docx", tmp_path / "result.docx"
    package, plan = generic_template(source, layout, variant * 7)
    before = dict(package.nodes)
    for root in package.parts.values():
        for text in list(root.iter(w("t"))):
            parent, index = text.getparent(), text.getparent().index(text)
            for char in text.text or "":
                item = etree.Element(w("t"))
                item.text = char
                item.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                parent.insert(index, item)
                index += 1
            parent.remove(text)
    package.reindex()
    plan = remap_plan(plan, before, package)
    package.write(source)
    document, seed_projects = generic_content()
    titles = [f"Work collection {variant}", f"证书与活动 {variant}"]
    for section, title in zip(document.sections, titles, strict=True):
        old = section.title
        section.title = title
        for field in plan.fields:
            if field.target == "section-title:" + old:
                field.target = "section-title:" + title
        for region in plan.repeats:
            if region.section == old:
                region.section = title
    document.personal.name = f"Independent Person {variant}"
    document.sections.append(
        ResumeSection(
            id="child",
            parent_id="recognition",
            title="Further credentials",
            entries=[{"id": "one", "details": "A newly added child record"}],
        )
    )
    projects = []
    for index in range(variant + 1):
        project = deepcopy(seed_projects[0])
        project["project_id"] = f"unique-{index}"
        project["content"].update(
            title=f"Independent project [{index}]",
            description=f"Unique body [{index}] " + "Long evidence. " * (variant * 7),
            role=f"Role [{index}]",
            stack=[f"Technology [{index}]"],
        )
        project["content"]["custom_fields"] = []
        projects.append(project)
    original, original_plan = source.read_bytes(), deepcopy(plan)
    fill_template(source, output, plan, document.model_dump(), projects)
    text = visible_text(output)
    assert text.count(document.personal.name) == 1 and "Old " not in text and "〔" not in text
    assert text.count("A newly added child record") == 1
    for project in projects:
        for key in ("title", "description", "role"):
            assert text.count(project["content"][key]) == 1
    # 同一映射再次用于隐藏栏目和空记录，不能泄漏上一份输出的内容
    document.sections[1].visible = False
    fill_template(source, output, plan, document.model_dump(), [])
    text = visible_text(output)
    assert "Independent project" not in text and "A newly added child record" not in text
    assert document.personal.name in text
    assert source.read_bytes() == original and plan == original_plan


@pytest.mark.parametrize("failure_count", [1, 2, 3])
@pytest.mark.parametrize("resume", [False, True])
def test_schema_failures_have_bounded_field_feedback(tmp_path, failure_count, resume):
    """第一次没有合法方案也可修正，最多三轮，每轮反馈字段路径且保留完整校验"""
    source = tmp_path / "original.docx"
    simple_template(source)
    original = source.read_bytes()

    class InvalidFirst(TemplateProvider):
        """模拟任意供应商忽略输出候选或返回错误字段类型"""

        def run_structured(self, **kwargs):
            """先返回结构错误，再返回真实方案，检查续聊和全量上下文都支持纠错"""
            if self.calls:
                request = json.loads(kwargs["prompt"].splitlines()[-1])
                assert request["format_validation"][0]["path"] == "photos.0"
                assert bool(kwargs["thread_id"]) is resume
            result = super().run_structured(**kwargs)
            if resume:
                kwargs["emit"]("thread", {"id": "own-test-session"})
            if len(self.calls) <= failure_count:
                raise StructuredOutputError(
                    "{}",
                    [
                        {
                            "loc": ("photos", 0),
                            "type": "literal_error",
                            "msg": "Use an image node",
                            "input": "non-image-container",
                        }
                    ],
                )
            return result

    provider = InvalidFirst()
    arguments = (
        TemplatePackage(source),
        provider,
        tmp_path,
        simple_document(),
        [],
        ProviderSettings(),
        threading.Event(),
        lambda *_: None,
    )
    if failure_count == 3:
        with pytest.raises(StructuredOutputError):
            analyze_plan(*arguments)
        assert len(provider.calls) == 3
    else:
        _, review, attempts, error = analyze_plan(*arguments)
        assert review["ready"] and attempts == failure_count + 1 and error is None
    assert source.read_bytes() == original


def test_cancellation_after_invalid_response_does_not_start_repair(tmp_path):
    """格式错误和取消同时发生时优先响应取消"""
    source = tmp_path / "original.docx"
    simple_template(source)
    flag = threading.Event()

    class CancelInvalid(TemplateProvider):
        """模拟请求完成前用户取消"""

        def run_structured(self, **kwargs):
            """置取消标记后返回无效结果"""
            self.calls.append(kwargs)
            flag.set()
            raise StructuredOutputError("{}", [])

    provider = CancelInvalid()
    with pytest.raises(Cancelled):
        analyze_plan(
            TemplatePackage(source),
            provider,
            tmp_path,
            simple_document(),
            [],
            ProviderSettings(),
            flag,
            lambda *_: None,
        )
    assert len(provider.calls) == 1
