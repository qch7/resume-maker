"""验证 AI 功能设置的保存、逐字段继承、提交快照及实际调用入口"""

import pytest
from fastapi.testclient import TestClient
from test_jobs import FakeProvider, wait_job
from test_template_analysis import TemplateProvider, completed, simple_document, simple_template

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.domain.models import AIResult, ProviderSettings
from resume_maker.domain.templates import TemplatePlan
from resume_maker.infrastructure.database import uid
from resume_maker.integrations.providers.codex import CodexProvider
from resume_maker.services.jobs import Jobs
from resume_maker.services.templates.tasks import Templates


def test_settings_persist_normalize_and_fill_defaults(tmp_path):
    """保存全部功能覆盖后重开应用仍保留，缺省字段补齐且模型空白会被清除"""
    config = Config(data_dir=tmp_path, token="test")
    app = create_app(config)
    app.state.services.db.set_setting("provider", {"model": "existing-model"})
    with TestClient(app, headers={"x-resume-token": "test"}) as client:
        initial = client.get("/api/settings").json()["provider"]
        assert initial == ProviderSettings(model="existing-model").model_dump()
        response = client.put(
            "/api/settings/provider",
            json={
                **initial,
                "model": " default-model ",
                "reasoning_effort": "high",
                "functions": {
                    function: {"model": f" {function}-model ", "reasoning_effort": "low"}
                    for function in (
                        "project_analysis",
                        "conversation",
                        "highlight_edit",
                        "template_analysis",
                        "template_repair",
                        "connection_check",
                    )
                },
            },
        )
        assert response.status_code == 200
        saved = response.json()
        assert saved["model"] == "default-model"
        assert saved["functions"]["template_analysis"]["model"] == "template_analysis-model"
    with TestClient(create_app(config), headers={"x-resume-token": "test"}) as client:
        assert client.get("/api/settings").json()["provider"] == saved
        cleared = client.put(
            "/api/settings/provider",
            json={**saved, "functions": {"conversation": {"model": "  "}}},
        ).json()
        assert cleared["functions"]["conversation"] == {"model": "", "reasoning_effort": ""}


@pytest.mark.parametrize(
    "invalid",
    [
        {"reasoning_effort": "unsupported"},
        {"functions": {"conversation": {"reasoning_effort": "unsupported"}}},
        {"functions": {"unknown": {"model": "test-model"}}},
    ],
)
def test_invalid_settings_do_not_replace_saved_configuration(tmp_path, invalid):
    """拒绝未知强度和功能标识，校验失败不能覆盖已保存的配置"""
    with TestClient(
        create_app(Config(data_dir=tmp_path, token="test")), headers={"x-resume-token": "test"}
    ) as client:
        original = client.get("/api/settings").json()["provider"]
        assert client.put("/api/settings/provider", json=invalid).status_code == 422
        assert client.get("/api/settings").json()["provider"] == original


@pytest.mark.parametrize(
    "kind,scope,expected",
    [
        ("analysis", "all", ("analysis-model", "medium")),
        ("chat", "all", ("default-model", "low")),
        ("chat", "highlight:one", ("highlight-model", "xhigh")),
    ],
)
def test_project_buttons_use_independent_settings_snapshot(
    catalog, populated, tmp_path, kind, scope, expected
):
    """三个经历入口逐字段继承，排队后修改设置不会改变已提交任务"""
    provider = FakeProvider()
    jobs = Jobs(catalog.db, catalog, tmp_path / "data", provider)
    settings = ProviderSettings(
        model="default-model",
        reasoning_effort="medium",
        profile="custom",
        functions={
            "project_analysis": {"model": "analysis-model"},
            "conversation": {"reasoning_effort": "low"},
            "highlight_edit": {"model": "highlight-model", "reasoning_effort": "xhigh"},
        },
    )
    catalog.db.set_setting("provider", settings.model_dump())
    conv = catalog.db.all("SELECT * FROM conversations")[0]
    job = jobs.submit(conv["id"], "配置测试", kind, populated["id"], scope, uid())
    catalog.db.set_setting("provider", ProviderSettings(model="next-model").model_dump())
    jobs.start()
    try:
        assert wait_job(catalog, job["id"])["status"] == "completed"
        actual = provider.calls[0]["settings"]
        assert (actual.model, actual.reasoning_effort) == expected
        assert actual.profile == "custom"
        followup = jobs.submit(conv["id"], "继续", "chat", populated["id"], "all", uid())
        assert wait_job(catalog, followup["id"])["status"] == "completed"
        assert provider.calls[-1]["settings"].model == "next-model"
        assert provider.calls[-1]["settings"].reasoning_effort == ""
        assert (
            provider.calls[-1]["thread"] == catalog.conversation(conv["id"])["provider_thread_id"]
        )
    finally:
        jobs.stop()


def test_connection_check_uses_its_override_and_inherits_after_reset(tmp_path, monkeypatch):
    """连接测试采用独立配置，清空覆盖后立即继承全局默认"""
    calls = []

    def run(self, **kwargs):
        """记录连接测试实参以免消耗真实模型额度"""
        calls.append(kwargs["settings"])
        return AIResult(reply="连接成功", experience=None, changes=[], questions=[])

    monkeypatch.setattr(CodexProvider, "run", run)
    with TestClient(
        create_app(Config(data_dir=tmp_path, token="test")), headers={"x-resume-token": "test"}
    ) as client:
        settings = {"model": "default-model", "reasoning_effort": "high"}
        for override, expected in (
            ({"model": "check-model", "reasoning_effort": "minimal"}, ("check-model", "minimal")),
            ({"model": "", "reasoning_effort": ""}, ("default-model", "high")),
        ):
            client.put(
                "/api/settings/provider",
                json={
                    **settings,
                    "functions": {"connection_check": override},
                },
            ).raise_for_status()
            response = client.post("/api/providers/codex/check")
            assert response.status_code == 200 and response.json()["ok"]
            assert (calls[-1].model, calls[-1].reasoning_effort) == expected


class ThreeRoundProvider(TemplateProvider):
    """前两轮留下不同的待修正方案，第三轮补齐姓名"""

    def run_structured(self, **kwargs):
        """触发完整三轮识别以检查强度不会被内部策略覆盖"""
        plan = super().run_structured(**kwargs)
        if len(self.calls) < 3:
            plan.fields = []
            plan.warnings = [f"待修正 {len(self.calls)}"]
        return plan


def test_template_recognition_and_both_repair_buttons_use_selected_settings(catalog, tmp_path):
    """识别三轮固定使用用户配置，两种人工完善入口使用各自提交时的覆盖"""
    source = tmp_path / "source.docx"
    simple_template(source)
    provider = ThreeRoundProvider(block=True)
    service = Templates(catalog, tmp_path, provider)
    catalog.db.set_setting(
        "provider",
        {
            "model": "default-model",
            "reasoning_effort": "medium",
            "functions": {
                "template_analysis": {"model": "template-model", "reasoning_effort": "low"}
            },
        },
    )
    try:
        started = service.analyze(source, simple_document())
        assert provider.started.wait(2)
        catalog.db.set_setting(
            "provider",
            {
                "model": "new-default",
                "reasoning_effort": "high",
                "functions": {
                    "template_repair": {"model": "repair-model", "reasoning_effort": "xhigh"}
                },
            },
        )
        provider.release.set()
        task = completed(service, started["id"])
        assert task["status"] == "completed" and task["attempts"] == 3
        assert all(
            (call["settings"].model, call["settings"].reasoning_effort) == ("template-model", "low")
            for call in provider.calls
        )
        for feedback in ("", "请按说明调整"):
            repaired = service.repair(
                task["id"],
                TemplatePlan.model_validate(task["plan"]),
                simple_document(),
                [],
                feedback,
            )
            assert completed(service, repaired["id"])["status"] == "completed"
            settings = provider.calls[-1]["settings"]
            assert (settings.model, settings.reasoning_effort) == ("repair-model", "xhigh")
    finally:
        provider.release.set()
        service.stop()


@pytest.mark.parametrize("override", [{"model": "another-model"}, {"reasoning_effort": "high"}])
def test_changed_template_settings_do_not_reuse_old_model_cache(catalog, tmp_path, override):
    """切换模板模型或强度后重新识别，相同设置仍复用已通过校验的结果"""
    source = tmp_path / "source.docx"
    simple_template(source)
    provider = TemplateProvider()
    service = Templates(catalog, tmp_path, provider)
    try:
        completed(service, service.analyze(source, simple_document())["id"])
        cached = completed(service, service.analyze(source, simple_document())["id"])
        assert cached["reused"] and len(provider.calls) == 1
        catalog.db.set_setting("provider", {"functions": {"template_analysis": override}})
        changed = completed(service, service.analyze(source, simple_document())["id"])
        assert not changed["reused"] and len(provider.calls) == 2
    finally:
        service.stop()
