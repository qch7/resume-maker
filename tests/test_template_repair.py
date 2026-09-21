"""自动修正、错误隔离和人工方案保护的行为回归"""

import json

import pytest
from docx import Document
from fastapi.testclient import TestClient
from test_template_analysis import TemplateProvider, completed, simple_document, simple_template
from test_template_mapping import make_template

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.domain.templates import TemplatePlan
from resume_maker.integrations.word.templates.mapping import TemplatePackage
from resume_maker.services.templates.analysis import complete_labels
from resume_maker.services.templates.tasks import Templates


class RepairProvider(TemplateProvider):
    """首轮故意遗漏姓名，后续可修正、失败或返回退步方案"""

    def __init__(self, outcome="complete"):
        """记录修正策略及每次调用，使用同一份无个人信息模板"""
        super().__init__()
        self.outcome = outcome

    def run_structured(self, **kwargs):
        """模拟模型根据反馈修正映射"""
        plan = super().run_structured(**kwargs)
        if len(self.calls) == 1 or self.outcome == "unchanged":
            plan.fields = []
        elif self.outcome == "failure":
            raise RuntimeError("模拟第二轮不可用")
        elif self.outcome == "worse":
            plan.fields[0].node = "nonexistent"
        return plan


def test_ai_repairs_its_own_missing_fields(catalog, tmp_path):
    """首轮遗漏会自动反馈给 AI，完整结果才显示为可试填并不传当前资料值"""
    source = tmp_path / "source.docx"
    simple_template(source)
    provider = RepairProvider()
    service = Templates(catalog, tmp_path, provider)
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
    service = Templates(catalog, tmp_path, provider)
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
