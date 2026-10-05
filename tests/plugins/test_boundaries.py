"""模型保护、资源校验和插件缺失后的可见行为"""

import json
import threading

import pytest

from resume_maker.domain.extensions import display_document
from resume_maker.domain.models import ProviderSettings
from resume_maker.infrastructure.execution import Execution, Sandbox
from resume_maker.integrations.privacy_gateway import PrivacyGateway
from resume_maker.sdk.model import ProviderError


def test_gateway_protects_any_transport_and_rejects_images_without_ocr(tmp_path):
    """不依赖供应商类即可脱敏和还原，缺少图片保护时不能降级发送原图"""
    calls = []

    def transport(payload, *_args, **_kwargs):
        """只接收脱敏文字并返回对应占位符"""
        calls.append(payload)
        assert "合成敏感姓名" not in payload["input"]
        return json.dumps(
            {"reply": payload["input"], "experience": None, "changes": [], "questions": []}
        )

    gateway = PrivacyGateway(runner=transport).with_private_data(
        {"personal": {"name": "合成敏感姓名"}}
    )
    options = dict(
        workspace=tmp_path,
        prompt="合成敏感姓名",
        thread_id=None,
        settings=ProviderSettings(),
        cancelled=threading.Event(),
        emit=lambda *_: None,
    )
    result = gateway.run(**options)
    assert result.reply == "合成敏感姓名"
    with pytest.raises(ProviderError, match="OCR"):
        gateway.run_structured(
            result_model=type(result), images=[tmp_path / "missing.png"], **options
        )
    assert len(calls) == 1


def test_execution_grants_are_bound_and_single_use(tmp_path):
    """更改命令、重复使用和不满足的隔离保证都不能进入执行后端"""
    calls = []

    class Backend:
        """合成平台明确只提供进程回收保证"""

        capabilities = {"process_cleanup": True}

    execution = Execution(lambda command, **kwargs: calls.append(command))
    sandbox = Sandbox(execution, Backend())
    grant = sandbox.authorize(
        "example", "plugin.worker", 1, ["process_cleanup"], command=["synthetic"], cwd=tmp_path
    )
    with pytest.raises(Exception, match="不符合"):
        execution.execute(grant, ["different"], cwd=tmp_path)
    execution.execute(grant, ["synthetic"], cwd=tmp_path)
    with pytest.raises(Exception, match="失效"):
        execution.execute(grant, ["synthetic"], cwd=tmp_path)
    with pytest.raises(Exception, match="无法提供"):
        sandbox.authorize(
            "example",
            "plugin.worker",
            1,
            ["os_network_isolation"],
            command=["synthetic"],
            cwd=tmp_path,
        )
    assert calls == [["synthetic"]]


def test_unknown_extensions_require_explicit_plain_text_display():
    """缺失插件资料仍然保留，无法解释的内容不会无提示漏出简历"""
    document = {
        "sections": [],
        "extensions": {"community.example": {"version": 1, "payload": "keep"}},
    }
    with pytest.raises(ValueError, match="默认展示"):
        display_document(document)
    document["extensions"]["community.example"]["display"] = {
        "title": "附加能力",
        "text": "合成内容",
    }
    displayed = display_document(document)
    assert displayed["sections"][0]["entries"][0]["details"] == "合成内容"
    assert document["sections"] == []


def test_execution_rejects_environment_material_and_revocation_changes(tmp_path):
    """凭据环境和输入被替换或权限撤销后，旧授权不能启动进程"""
    source = tmp_path / "material.txt"
    source.write_text("synthetic", encoding="utf-8")
    execution = Execution(lambda *_args, **_kwargs: None)
    grant = execution.authorize(
        "test",
        "plugin.worker",
        1,
        command=["synthetic"],
        cwd=tmp_path,
        env={"TEST": "one"},
        materials=[source],
    )
    with pytest.raises(Exception, match="环境"):
        execution.execute(grant, ["synthetic"], cwd=tmp_path, env={"TEST": "two"})
    source.write_text("changed", encoding="utf-8")
    with pytest.raises(Exception, match="材料"):
        execution.execute(grant, ["synthetic"], cwd=tmp_path, env={"TEST": "one"})
    source.write_text("synthetic", encoding="utf-8")
    execution.revoke_owner("test")
    with pytest.raises(Exception, match="失效"):
        execution.execute(grant, ["synthetic"], cwd=tmp_path, env={"TEST": "one"})


def test_privacy_policy_change_cancels_existing_material_context(tmp_path):
    """保护规则变化后即使传输返回正常结果也不能发布旧请求结果"""
    from resume_maker.infrastructure.database import Database
    from resume_maker.integrations.privacy_store import PrivacyStore
    from resume_maker.plugin_packages.sys_privacy.services.privacy import Privacy
    from resume_maker.sdk.model import Cancelled

    db = Database(tmp_path / "resume.db")
    store = PrivacyStore(db)
    privacy = Privacy(db, store)

    def transport(_payload, _settings, _environment, cancelled, _emit):
        """模拟请求发送后用户收紧保护规则"""
        privacy.save_terms(["新增敏感词"], 0)
        assert cancelled.is_set()
        return '{"reply":"synthetic","experience":null,"changes":[],"questions":[]}'

    gateway = PrivacyGateway(runner=transport, privacy=store)
    with pytest.raises(Cancelled):
        gateway.run(
            workspace=tmp_path,
            prompt="synthetic",
            thread_id=None,
            settings=ProviderSettings(),
            cancelled=threading.Event(),
            emit=lambda *_: None,
        )
    assert privacy.requests()[0]["status"] == "cancelled"
