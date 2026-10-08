"""共享设置和未发送输入的并发保存保护"""

import pytest

from resume_maker.core.errors import Problem
from resume_maker.domain.models import ProviderSettings
from resume_maker.plugin_packages.ext_ai_conversation.services.conversations import Conversations
from resume_maker.plugin_packages.ext_ai_conversation.services.jobs import Jobs
from resume_maker.plugin_packages.sys_settings.services.settings import Settings
from resume_maker.sdk.records import uid
from tests.support.jobs import FakeProvider


def test_provider_conflict_preserves_model_and_legacy_settings(catalog, tmp_path):
    """旧数据无需迁移，旧窗口不能用整份配置撤销新模型选择"""
    catalog.db.set_setting("provider", {"profile": "旧配置"})
    settings = Settings(catalog.db, tmp_path)
    first = ProviderSettings.model_validate(settings.get()["provider"])
    second = first.model_copy(update={"profile": "窗口乙"})
    saved = settings.save_provider(first.model_copy(update={"model": "窗口甲模型"}))
    assert saved.version == 1
    with pytest.raises(Problem) as failure:
        settings.save_provider(second)
    assert failure.value.status == 409
    assert settings.get()["provider"] == saved.model_dump()


def test_conversation_requires_input_baseline_and_preserves_conflicts(catalog, project):
    """双方从空输入开始时仅首份保存成功，核对后可显式合并"""
    conversations = Conversations(catalog, storage=catalog.db)
    conversation = conversations.create_conversation(project["id"], "测试")
    identifier = conversation["id"]
    with pytest.raises(Problem) as missing:
        conversations.patch_conversation(identifier, {"input_draft": "无基线"})
    assert missing.value.status == 422
    confirmed = conversations.patch_conversation(
        identifier, {"input_draft": "甲未发送", "expected_input_draft": ""}
    )
    assert confirmed["input_draft"] == "甲未发送"
    with pytest.raises(Problem) as stale:
        conversations.patch_conversation(
            identifier, {"input_draft": "乙未发送", "expected_input_draft": ""}
        )
    assert stale.value.status == 409
    assert conversations.conversation(identifier)["input_draft"] == "甲未发送"
    merged = conversations.patch_conversation(
        identifier, {"input_draft": "甲未发送\n乙未发送", "expected_input_draft": "甲未发送"}
    )
    assert merged["input_draft"] == "甲未发送\n乙未发送"


def test_sending_does_not_clear_another_windows_new_input(catalog, project, tmp_path):
    """发送甲消息前乙已保存新输入，排队只清除与所发消息相同的草稿"""
    conversations = Conversations(catalog, storage=catalog.db)
    identifier = conversations.create_conversation(project["id"], "测试")["id"]
    conversations.patch_conversation(
        identifier, {"input_draft": "乙下一轮输入", "expected_input_draft": ""}
    )
    jobs = Jobs(catalog.db, catalog, tmp_path / "data", FakeProvider())
    try:
        job = jobs.submit(identifier, "甲当前消息", "chat", project["head_revision"], "all", uid())
        assert job["status"] == "queued"
        assert conversations.conversation(identifier)["input_draft"] == "乙下一轮输入"
    finally:
        jobs.stop()
