"""校验 Codex 公开动态不会混入推理、命令参数和最终映射"""

import json
import os
import threading
from io import StringIO
from types import SimpleNamespace

import pytest

from resume_maker.domain.models import ProviderSettings
from resume_maker.domain.templates import TemplatePlan
from resume_maker.integrations.providers.base import ProviderError, StructuredOutputError
from resume_maker.integrations.providers.codex import CodexProvider, structured_text


@pytest.mark.parametrize("fenced", [False, True])
@pytest.mark.parametrize("reconnected", [False, True])
def test_public_events_and_resumed_schema(monkeypatch, tmp_path, fenced, reconnected):
    """模拟 CLI 事件；保留会话和用量；同时只向界面发布公开摘要"""
    plan = TemplatePlan(
        summary="最终结果", fields=[], repeats=[], photos=[], keep=[], remove=[], warnings=[]
    )
    events = [
        {"type": "thread.started", "thread_id": "own-session"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "reasoning", "text": "private reasoning"}},
        {
            "type": "item.started",
            "item": {"type": "command_execution", "command": "secret command"},
        },
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "正在核对栏目 api_key=hidden"},
        },
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": f"```json\n{plan.model_dump_json()}\n```"
                if fenced
                else plan.model_dump_json(),
            },
        },
        {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}},
    ]
    if reconnected:
        events.insert(2, {"type": "error", "message": "Reconnecting after stream interrupted"})
    commands = []
    environments = []

    class Process:
        """以可读取流替代真实 CLI且不触发外部模型"""

        def __init__(self, command, **kwargs):
            """记录命令并准备模拟输出及空错误流"""
            commands.append(command)
            environments.append(kwargs["env"])
            self.stdin = StringIO()
            self.stdout = StringIO("\n".join(json.dumps(event) for event in events) + "\n")
            self.stderr = StringIO()

        def wait(self, timeout):
            """模拟进程正常结束"""
            return 0

        def poll(self):
            """避免测试触发真实进程回收"""
            return 0

    monkeypatch.setattr("resume_maker.integrations.providers.codex.subprocess.Popen", Process)
    monkeypatch.setattr(CodexProvider, "executable", lambda *_: "codex")
    emitted = []
    monkeypatch.delenv("RESUME_TEST_ROUTE", raising=False)
    result = CodexProvider(environment={"RESUME_TEST_ROUTE": "isolated"}).run_structured(
        result_model=TemplatePlan,
        workspace=tmp_path,
        prompt="测试",
        thread_id="own-session",
        settings=ProviderSettings(model="test-model", reasoning_effort="medium", profile="test"),
        cancelled=threading.Event(),
        emit=lambda kind, data: emitted.append((kind, data)),
    )
    assert result == plan
    assert environments[0]["RESUME_TEST_ROUTE"] == "isolated"
    assert "RESUME_TEST_ROUTE" not in os.environ
    visible = json.dumps([data for kind, data in emitted if kind == "activity"], ensure_ascii=False)
    assert "正在核对栏目" in visible and "会话已连接" in visible
    assert all(
        value not in visible
        for value in ("private reasoning", "secret command", "hidden", "最终结果")
    )
    assert ("thread", {"id": "own-session"}) in emitted
    assert "--output-schema" in commands[0] and commands[0][-3:] == ["resume", "own-session", "-"]

    assert 'model_reasoning_effort="medium"' in commands[0]
    assert commands[0][commands[0].index("--model") + 1] == "test-model"
    assert commands[0][commands[0].index("--profile") + 1] == "test"
    CodexProvider().run_structured(
        result_model=TemplatePlan,
        workspace=tmp_path,
        prompt="普通任务",
        thread_id=None,
        settings=ProviderSettings(),
        cancelled=threading.Event(),
        emit=lambda *_: None,
    )
    assert not any("model_reasoning_effort" in value for value in commands[1])
    assert "--model" not in commands[1] and "--profile" not in commands[1]
    assert "RESUME_TEST_ROUTE" not in environments[1]
    for thread_id in (None, "own-session"):
        for effort in ("minimal", "low", "medium", "high", "xhigh"):
            CodexProvider().run_structured(
                result_model=TemplatePlan,
                workspace=tmp_path,
                prompt="配置覆盖",
                thread_id=thread_id,
                settings=ProviderSettings(model="changed-model", reasoning_effort=effort),
                cancelled=threading.Event(),
                emit=lambda *_: None,
            )
            assert commands[-1][commands[-1].index("--model") + 1] == "changed-model"
            assert f'model_reasoning_effort="{effort}"' in commands[-1]


@pytest.mark.parametrize(
    "message",
    [
        "{}\n```json\n{}\n```",
        "```json\n{}\n```\n[]",
        "```json\n{}\n```\n```json\n{}\n```",
        '说明：{"x": 1}',
        "```json\n{}",
    ],
)
def test_structured_message_cannot_hide_extra_text_or_multiple_results(message):
    """去包装不能吞掉块外结构化数据、多个结果或截断内容。"""
    with pytest.raises(ValueError):
        json.loads(structured_text(message))


@pytest.mark.parametrize(
    "prefix,suffix", [("说明如下：\n", ""), ("", "\n映射完成。"), ("已检查 `n1`。\n", "\n结束。")]
)
def test_unique_json_fence_allows_prose_wrapper(prefix, suffix):
    """唯一完整代码块可以忽略非数据说明；字段和节点仍须通过同一严格模型校验。"""
    assert json.loads(structured_text(prefix + '```json\n{"x":1}\n```' + suffix)) == {"x": 1}


def test_failed_turn_remains_failure_even_with_valid_json(monkeypatch, tmp_path):
    """重连未成功完成时不能仅凭中间 JSON 把失败判为通过。"""
    plan = TemplatePlan(
        summary="中间结果", fields=[], repeats=[], photos=[], keep=[], remove=[], warnings=[]
    )
    events = [
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": plan.model_dump_json()},
        },
        {"type": "turn.failed", "error": "transport unavailable"},
    ]

    def launch(*args, **kwargs):
        """构造退出码正常但当前轮次失败的 CLI 事件流。"""
        return SimpleNamespace(
            stdin=StringIO(),
            stdout=StringIO("\n".join(json.dumps(event) for event in events)),
            stderr=StringIO(),
            wait=lambda **_: 0,
            poll=lambda: 0,
        )

    monkeypatch.setattr("resume_maker.integrations.providers.codex.subprocess.Popen", launch)
    monkeypatch.setattr(CodexProvider, "executable", lambda *_: "codex")
    with pytest.raises(ProviderError, match="transport unavailable"):
        CodexProvider().run_structured(
            result_model=TemplatePlan,
            workspace=tmp_path,
            prompt="test",
            thread_id=None,
            settings=ProviderSettings(),
            cancelled=threading.Event(),
            emit=lambda *_: None,
        )


def test_invalid_output_exposes_field_path_for_repair(monkeypatch, tmp_path):
    """结构校验失败携带真实字段路径，而不是只有不可用于修正的通用报错。"""
    response = json.dumps(
        {
            "summary": [],
            "fields": [],
            "repeats": [],
            "keep": [],
            "remove": [],
            "photos": [],
            "warnings": [],
        }
    )
    events = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": response}},
        {"type": "turn.completed", "usage": {}},
    ]

    def launch(*args, **kwargs):
        """模拟已成功连接但返回错误字段类型的模型。"""
        return SimpleNamespace(
            stdin=StringIO(),
            stdout=StringIO("\n".join(json.dumps(e) for e in events)),
            stderr=StringIO(),
            wait=lambda **_: 0,
            poll=lambda: 0,
        )

    monkeypatch.setattr("resume_maker.integrations.providers.codex.subprocess.Popen", launch)
    monkeypatch.setattr(CodexProvider, "executable", lambda *_: "codex")
    with pytest.raises(StructuredOutputError) as caught:
        CodexProvider().run_structured(
            result_model=TemplatePlan,
            workspace=tmp_path,
            prompt="test",
            thread_id=None,
            settings=ProviderSettings(),
            cancelled=threading.Event(),
            emit=lambda *_: None,
        )
    assert caught.value.issues[0]["path"] == "summary"
    assert caught.value.issues[0]["type"] == "string_type"
    assert caught.value.response == response


def test_startup_failure_reports_cli_diagnostic_instead_of_broken_pipe(monkeypatch, tmp_path):
    """配置无效导致 CLI 提前退出时保留真正错误，不能被 stdin BrokenPipe 覆盖。"""

    class ClosedInput(StringIO):
        """模拟 CLI 已经关闭输入管道。"""

        def write(self, value):
            """写入尚未启动的模型请求时抛出管道错误。"""
            raise BrokenPipeError("closed")

    class Process:
        """模拟配置解析失败而提前退出的 CLI。"""

        def __init__(self, *args, **kwargs):
            """保留错误流供正常收集路径读取。"""
            self.stdin, self.stdout = ClosedInput(), StringIO()
            self.stderr = StringIO("Invalid model catalog: missing slug\n")

        def wait(self, timeout):
            """配置错误退出码。"""
            return 1

        def poll(self):
            """进程已退出，无需回收。"""
            return 1

    monkeypatch.setattr("resume_maker.integrations.providers.codex.subprocess.Popen", Process)
    monkeypatch.setattr(CodexProvider, "executable", lambda *_: "codex")
    with pytest.raises(ProviderError, match="Invalid model catalog"):
        CodexProvider().run_structured(
            result_model=TemplatePlan,
            workspace=tmp_path,
            prompt="test",
            thread_id=None,
            settings=ProviderSettings(),
            cancelled=threading.Event(),
            emit=lambda *_: None,
        )
