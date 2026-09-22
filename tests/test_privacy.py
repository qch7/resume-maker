"""验证外发请求不含已知身份值，模型不能通过附件、会话或工具绕过出口"""

import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.domain.models import ProviderSettings
from resume_maker.integrations.privacy import TOKEN, Redactor
from resume_maker.integrations.privacy_store import PrivacyStore
from resume_maker.integrations.providers.base import Cancelled, ProviderError, StructuredOutputError
from resume_maker.integrations.providers.codex import CodexProvider
from resume_maker.integrations.providers.connection import connection
from resume_maker.integrations.source_access import SourceAccess
from resume_maker.integrations.source_context import source_context
from resume_maker.integrations.sources import project_sources


def reply(text="完成"):
    """构造不含额外行为的合成模型结果"""
    return {"reply": text, "experience": None, "changes": [], "questions": []}


def provider_at(tmp_path, handler, db=None, *, source_handler=None):
    """注入只接收安全材料的 CLI 替身，不访问用户配置或真实模型"""

    def runner(payload, settings, environment, cancelled, emit, *, source_access=None):
        """回显可控的结构化结果以检查本机还原"""
        result = source_handler(payload, source_access) if source_handler else handler(payload)
        return json.dumps(result, ensure_ascii=False)

    return CodexProvider(privacy=PrivacyStore(db), runner=runner)


def run(provider, tmp_path, prompt, **options):
    """调用真实隐私出口并使用可控的取消信号"""
    return provider.run(
        workspace=tmp_path / "private-workspace",
        prompt=prompt,
        thread_id="old-private-session",
        settings=ProviderSettings(),
        cancelled=options.pop("cancelled", threading.Event()),
        emit=lambda *_: None,
        **options,
    )


def test_actual_request_masks_context_schema_and_restores_locally(tmp_path, catalog):
    """模拟供应商只看到占位符，输出和本地发送审计各自符合隐私边界"""
    values = ["测试甲", "13812345678", "person@example.invalid", "测试住宅甲"]
    catalog.db.set_setting("privacy_terms", values)
    seen = []

    def handle(request):
        """检查真实 HTTP 正文及鉴权，回显脱敏文字用于验证本地还原"""
        body = request
        seen.append(body)
        serialized = json.dumps(body, ensure_ascii=False)
        assert all(
            value not in serialized
            for value in [*values, "old-private-session", "private-workspace"]
        )
        assert body["transport"] == "codex-cli-sandbox" and "schema" in body
        return reply(body["input"])

    provider = provider_at(tmp_path, handle, catalog.db)
    prompt = " / ".join(values)
    assert run(provider, tmp_path, prompt).reply == prompt
    assert len(seen) == 1
    audit = catalog.db.setting("privacy_audit")
    assert audit[0]["payload"] == seen[0] and audit[0]["status"] == "completed"
    assert "synthetic-key" not in json.dumps(audit)
    assert not (tmp_path / "private-workspace").exists()


def test_saved_and_unsaved_documents_supply_sensitive_values(tmp_path, catalog):
    """尚未保存的表单和已保存的荣誉隐藏字段仍能保护自由聊天中的真实值"""
    catalog.db.set_setting(
        "honor:test", {"fields": {"recipient": "合成获奖人", "certificate_number": "HONOR-PRIVATE"}}
    )
    seen = []

    def handle(request):
        """核对未持久化的个人字段只以占位符发出"""
        seen.append(request)
        return reply()

    base = provider_at(tmp_path, handle, catalog.db)
    provider = base.with_private_data(
        {
            "personal": {
                "name": "合成姓名",
                "hidden_fields": ["name"],
                "custom_fields": [{"value": "合成单位"}],
            }
        }
    )
    run(provider, tmp_path, "合成姓名 合成单位 合成获奖人 HONOR-PRIVATE")
    assert all(
        value not in seen[0]["input"]
        for value in ("合成姓名", "合成单位", "合成获奖人", "HONOR-PRIVATE")
    )
    assert base.sensitive_values == set()


@pytest.mark.parametrize(
    "value",
    [
        "user@example.invalid",
        "138 1234 5678",
        "11010120000101123X",
        "姓名：测试甲",
        "证书编号：XYZ-123",
        "测试甲同学",
        "https://example.invalid/private",
        r"C:\Users\Private\data.txt",
        "/home/private/file",
        "192.168.9.11",
    ],
)
def test_unknown_common_identity_patterns_are_masked(value):
    """材料中新出现的常见身份格式不依赖已保存的资料"""
    redactor = Redactor()
    safe = redactor.prompt(value)
    assert safe != value and TOKEN.search(safe)
    assert redactor.restore(safe) == value


def test_escaped_values_secrets_and_structured_keys():
    """JSON 转义、字典键和凭据不能绕过脱敏，凭据永不通过占位符还原"""
    redactor = Redactor(["测试甲", "example-secret"])
    value = {
        "测试甲": "测试甲",
        "source": r'"\u6d4b\u8bd5\u7532"',
        "password": "example-secret",
        "notes": "example-secret",
    }
    safe = redactor.prompt("任务\n" + json.dumps(value))
    assert "测试甲" not in safe and "example-secret" not in safe
    assert "\\u6d4b" not in safe
    restored = redactor.restore(json.loads(safe.split("\n", 1)[1]))
    assert restored["测试甲"] == "测试甲"
    assert restored["password"] == restored["notes"] == "[凭据已移除]"


def test_structured_names_and_multiline_values(tmp_path):
    """无标签结构字段和跨行自定义值脱敏后仍能准确还原"""
    redactor = Redactor(["第一行\n第二行"])
    safe = redactor.prompt(json.dumps({"Name": "Synthetic Person", "notes": "第一行\n第二行"}))
    assert "Synthetic Person" not in safe
    restored = redactor.restore(json.loads(safe))
    assert restored["Name"] == "Synthetic Person" and restored["notes"] == "第一行\n第二行"
    assert json.loads(safe)["notes"].count("\n") == 1


def test_connection_inherits_profile_effort_and_overrides_without_executing_tools(tmp_path):
    """配置档继承的模型参数可显式覆盖，工具配置不会进入连接结果"""
    (tmp_path / "config.toml").write_text(
        'model="base"\nmodel_reasoning_effort="medium"\n'
        '[profiles.test]\nmodel="profile"\nmodel_reasoning_effort="high"\n'
        '[mcp_servers.private]\ncommand="never-execute"\n',
        encoding="utf-8",
    )
    env = {"CODEX_HOME": str(tmp_path), "OPENAI_API_KEY": "synthetic-key"}
    values, _ = connection(ProviderSettings(profile="test"), env)
    assert (values["model"], values["model_reasoning_effort"]) == ("profile", "high")
    assert "mcp_servers" not in values
    values, _ = connection(
        ProviderSettings(profile="test", model="override", reasoning_effort="low"), env
    )
    assert (values["model"], values["model_reasoning_effort"]) == ("override", "low")


@pytest.mark.parametrize("input_text", ["data:image/png;base64,AAAA", "A" * 600, "[[RM_fake]]"])
def test_encoded_payloads_and_forged_tokens_fail_closed(input_text):
    """图片编码和手工伪造的占位符不能伪装成普通文本外发"""
    with pytest.raises(ProviderError):
        Redactor().prompt(input_text)


@pytest.mark.parametrize("text", ["[[RM_aaaaaaaaaaaa_99]]", "[[RM_broken]]"])
def test_unknown_token_responses_are_rejected(tmp_path, text):
    """未知或损坏的占位符不能污染本机简历"""
    provider = provider_at(tmp_path, lambda _: reply(text))
    with pytest.raises(ProviderError):
        run(provider, tmp_path, "测试")


def test_validation_feedback_is_local_and_can_be_redacted_again(tmp_path):
    """格式错误反馈还原到本机后，下轮会重新脱敏而不会复用旧占位符"""

    def handle(request):
        """返回错误字段类型，使错误信息含本轮占位符"""
        token = TOKEN.search(request["input"])[0]
        return {**reply(), "reply": [token]}

    provider = provider_at(tmp_path, handle).with_private_data({"personal": {"name": "测试甲"}})
    with pytest.raises(StructuredOutputError) as caught:
        run(provider, tmp_path, "测试甲")
    assert "测试甲" in caught.value.response
    assert "[[RM_" not in json.dumps(caught.value.issues)
    safe = Redactor(["测试甲"]).prompt(json.dumps(caught.value.issues, ensure_ascii=False))
    assert "测试甲" not in safe


def test_cancelled_cli_marks_audit_without_publishing_result(tmp_path, catalog):
    """CLI 取消后只保存取消状态，不发布任何结果"""
    flag = threading.Event()

    def runner(*args):
        """模拟 CLI 等待期间用户发出取消"""
        flag.set()
        raise Cancelled("取消")

    provider = CodexProvider(privacy=PrivacyStore(catalog.db), runner=runner)
    with pytest.raises(Cancelled):
        run(provider, tmp_path, "测试", cancelled=flag)
    assert catalog.db.setting("privacy_audit")[0]["status"] == "cancelled"


def test_subscription_login_is_preserved_and_credentials_are_not_arguments(tmp_path):
    """订阅鉴权留给 CLI，供应商令牌只进入父进程环境"""
    (tmp_path / "config.toml").write_text('model="test"', encoding="utf-8")
    (tmp_path / "auth.json").write_text(json.dumps({"tokens": {"access_token": "private-token"}}))
    values, env = connection(
        ProviderSettings(), {"CODEX_HOME": str(tmp_path), "OPENAI_API_KEY": ""}
    )
    assert values["model"] == "test" and env["CODEX_HOME"] == str(tmp_path.resolve())
    assert "private-token" not in json.dumps([values, env])
    (tmp_path / "config.toml").write_text(
        'model="test"\n[model_providers.openai]\nbase_url="http://remote.invalid/v1"'
    )
    with pytest.raises(ProviderError, match="HTTPS"):
        connection(ProviderSettings(), {"CODEX_HOME": str(tmp_path), "OPENAI_API_KEY": "test"})


def test_source_bundle_excludes_private_files_and_preserves_line_numbers(
    tmp_path, catalog, project
):
    """本地采集不读取密钥或自身数据库，引用路径和行号仍对应原始源码"""
    root = Path(project["roots"][0])
    (root / ".env").write_text("SECRET=private")
    (root / "private.pem").write_text("private")
    (root / "main.py").write_text("# test\nprint('hello')\n")
    (root / "oversize.py").write_text("x = 1\n" * 22000)
    (root / "data").mkdir()
    (root / "data" / "resume.txt").write_text("private")
    sources = project_sources(project)
    value = source_context(sources, root / "data", threading.Event())
    with SourceAccess(sources, root / "data", Redactor(), threading.Event()) as access:
        rows = access.call("list_source_files", {})["results"]
        assert {row["path"] for row in rows} == {"README.md", "main.py", "oversize.py"}
        result = access.call("read_source", {"source": "source-0", "path": "main.py"})
        assert result["lines"][1] == {"line": 2, "text": "print('hello')"}
    assert str(root) not in json.dumps(value)


def test_privacy_api_requires_token_and_preview_does_not_store_raw_text(tmp_path):
    """本地检测不外发、不落盘，保存规则后重开实例仍然生效"""
    config = Config(data_dir=tmp_path, token="test")
    app = create_app(config)
    with TestClient(app) as client:
        assert client.get("/api/privacy").status_code == 401
        client.headers["x-resume-token"] = "test"
        assert client.put("/api/privacy/terms", json={"terms": ["测试甲"]}).status_code == 200
        assert client.put("/api/privacy/terms", json={"terms": []}).status_code == 409
        assert client.get("/api/privacy").json()["terms"] == ["测试甲"]
        preview = client.post("/api/privacy/preview", json={"text": "测试甲负责解析"}).json()
        assert "测试甲" not in preview["text"]
        assert client.get("/api/privacy/requests").json() == []
        store = PrivacyStore(app.state.services.db)
        for index in range(12):
            store.record({"input": str(index)}, 0)
        assert len(client.get("/api/privacy/requests").json()) == 10
        assert client.delete("/api/privacy/requests").status_code == 200
        assert client.get("/api/privacy/requests").json() == []
    assert create_app(config).state.services.db.setting("privacy_terms") == ["测试甲"]


def test_source_audit_retention_does_not_limit_reading(tmp_path, catalog):
    """超过审计保留数量仍可读取，动态占位符在最终结果中准确还原"""
    root = tmp_path / "source"
    root.mkdir()
    (root / "main.py").write_text("late@example.invalid", encoding="utf-8")
    caches = []

    def handle(payload, access):
        """持续请求相同材料以跨过记录保留边界，不额外引入模型额度"""
        assert "late@example.invalid" not in payload["input"]
        caches.append(Path(access.directory.name))
        for _ in range(25):
            result = access.call("read_source", {"source": "source-0", "path": "main.py"})
        return reply(result["lines"][0]["text"])

    provider = provider_at(tmp_path, None, catalog.db, source_handler=handle)
    result = run(
        provider,
        tmp_path,
        "分析",
        sources=[{"id": "source-0", "path": str(root)}],
        data_dir=tmp_path / "data",
    )
    assert result.reply == "late@example.invalid"
    audit = catalog.db.setting("privacy_audit")[0]
    assert audit["payload"]["source_tool_calls"] == 25
    assert len(audit["payload"]["source_tools"]) == 20
    assert "late@example.invalid" not in json.dumps(audit)
    assert all(not path.exists() for path in caches)
