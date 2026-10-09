"""自动修正、错误隔离和人工方案保护的行为回归"""

import json
import threading

import pytest
from docx import Document
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.domain.models import ProviderSettings
from resume_maker.domain.templates import TemplatePlan
from resume_maker.infrastructure.assets import Assets
from resume_maker.integrations.word.templates.mapping import TemplatePackage
from resume_maker.plugin_packages.ext_template_adapter.services.templates.tasks import Templates
from resume_maker.plugin_packages.ext_template_ai.services.templates.analysis import (
    analyze_plan,
    complete_labels,
)
from resume_maker.plugin_packages.ext_template_ai.services.templates.analysis_driver import (
    TemplateAnalysis,
)
from resume_maker.plugin_packages.sys_resume.services.resumes import Resumes
from resume_maker.sdk.model import Cancelled, StructuredOutputError
from tests.support.documents import make_template
from tests.support.templates import (
    RepairProvider,
    TemplateProvider,
    completed,
    simple_document,
    simple_template,
)


def test_ai_repairs_its_own_missing_fields(catalog, tmp_path):
    """首轮遗漏会自动反馈给 AI，完整结果才显示为可试填并不传当前资料值"""
    source = tmp_path / "source.docx"
    simple_template(source)
    provider = RepairProvider()
    service = Templates(
        Resumes(catalog, storage=catalog.db, assets=catalog.assets),
        tmp_path,
        provider,
        storage=catalog.db,
        analysis=TemplateAnalysis(),
        assets=Assets(catalog.db, tmp_path),
    )
    task = completed(service, service.analyze(source, simple_document())["id"])
    assert task["review"]["ready"] and task["attempts"] == 2
    context = json.loads(provider.calls[1]["prompt"].split("\n")[-1])
    assert context["validation"]["unresolved"]
    assert "personal.name" in context["validation"]["missing"]
    assert "新的用户资料" not in provider.calls[1]["prompt"]


@pytest.mark.parametrize("outcome", ["failure", "worse", "unchanged"])
def test_repair_preserves_best_result_and_is_bounded(catalog, tmp_path, outcome):
    """修正失败、退步或停滞时结束重试并保留已有结果"""
    source = tmp_path / "source.docx"
    simple_template(source)
    provider = RepairProvider(outcome)
    service = Templates(
        Resumes(catalog, storage=catalog.db, assets=catalog.assets),
        tmp_path,
        provider,
        storage=catalog.db,
        analysis=TemplateAnalysis(),
        assets=Assets(catalog.db, tmp_path),
    )
    task = completed(service, service.analyze(source, simple_document())["id"])
    assert task["status"] == "completed" and not task["review"]["ready"]
    assert not task["plan"]["fields"]
    assert len(provider.calls) <= 3
    assert bool(task["repair_error"]) == (outcome == "failure")


def test_one_bad_region_does_not_mark_other_mappings_unresolved(tmp_path):
    """一处样本字段错误只产生可定位的问题，后面的照片、栏目及固定文字仍被统计"""
    package, plan = make_template(tmp_path / "source.docx")
    assert package.review(plan)["ready"]
    plan.repeats[0].fields[0].node = plan.fields[0].node
    review = package.review(plan)
    assert not review["ready"] and review["errors"]
    assert not review["unresolved"]
    assert review["issues"][0]["nodes"]


def test_only_known_empty_labels_are_completed(tmp_path):
    """自动补齐固定标签，未知人名、经历和电话号码仍交给 AI 或用户判断"""
    source = tmp_path / "source.docx"
    doc = Document()
    for text in ("项目名称：", "张测试", "13800000000", "独立完成研发工作"):
        doc.add_paragraph(text)
    doc.save(source)
    package = TemplatePackage(source)
    plan = TemplatePlan(
        summary="测试", fields=[], repeats=[], photos=[], keep=[], remove=[], warnings=[]
    )
    updated = complete_labels(package, plan)
    review = package.review(updated)
    assert len(updated.keep) == 1 and not plan.keep
    assert len(review["unresolved"]) == 3


def test_user_feedback_repair_preserves_original_and_validates_current_profile(tmp_path):
    """文字调整创建独立任务并将人工方案和当前缺少字段反馈给模型"""
    source = tmp_path / "source.docx"
    simple_template(source)
    provider = TemplateProvider()
    app = create_app(Config(data_dir=tmp_path / "data", token="test"), provider)
    with TestClient(app) as client:
        service = app.state.services.templates
        original = completed(service, service.analyze(source, simple_document())["id"])
        headers = {"x-resume-token": "test"}
        body = {"plan": original["plan"], "document": simple_document().model_dump(), "items": []}
        body["document"]["personal"]["phone"] = "10000000000"
        review = client.post(
            f"/api/templates/analyses/{original['id']}/review", json=body, headers=headers
        )
        assert review.json()["ready"] and not review.json()["missing"]
        assert any("电话" in notice for notice in review.json()["notices"])
        endpoint = f"/api/templates/analyses/{original['id']}/repair"
        body["feedback"] = "保留姓名位置，再次检查"
        assert client.post(endpoint, json=body).status_code == 401
        body["document"] = simple_document().model_dump()
        response = client.post(endpoint, json=body, headers=headers)
        assert response.status_code == 200 and response.json()["id"] != original["id"]
        task = completed(service, response.json()["id"])
        assert task["review"]["ready"]
        assert "保留姓名位置，再次检查" in provider.calls[-1]["prompt"]
        assert service.get(original["id"])["plan"] == original["plan"]
        assert not app.state.services.db.all("SELECT * FROM templates")


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
