"""验证 CLI 工具事件、公开进度、失败诊断和结构化回复包装"""

import json
import os
import sys
import threading
from contextlib import contextmanager

import pytest

from resume_maker.domain.models import ProviderSettings
from resume_maker.integrations.providers import cli
from resume_maker.integrations.providers.base import ProviderError
from resume_maker.integrations.providers.codex import structured_text
from resume_maker.integrations.providers.process import execute


@pytest.fixture
def cli_stream(tmp_path, monkeypatch):
    """用合成事件驱动真实解析入口，不访问本机配置、登录或供应商"""
    stream = []

    @contextmanager
    def workspace():
        """在测试临时目录准备隔离材料和控制文件"""
        (tmp_path / "control").mkdir()
        (tmp_path / "materials").mkdir()
        yield tmp_path

    @contextmanager
    def credentials(root, env, cancelled):
        """提供空白 CLI home，避免读取真实凭据"""
        home = root / "control/codex-home"
        home.mkdir()
        yield {**env, "CODEX_HOME": str(home)}

    def execute_stream(command, **kwargs):
        """模拟版本检查和 CLI 逐行事件，异常立即终止后续事件"""
        if "--version" in command:
            return "codex-cli 0.154.0"
        for value in stream:
            kwargs["event"](value)

    monkeypatch.setattr(cli, "connection", lambda *_: ({}, {"OPENAI_API_KEY": "synthetic-cli-key"}))
    monkeypatch.setattr(cli, "workspace", workspace)
    monkeypatch.setattr(cli, "isolated_credentials", credentials)
    monkeypatch.setattr(cli, "native_executable", lambda *_: "synthetic-cli")
    monkeypatch.setattr(cli, "write_catalog", lambda root, selected: str(root / "catalog.json"))
    monkeypatch.setattr(cli, "execute", execute_stream)

    def run(events, emit=lambda *_: None):
        """将给定事件流送入本轮 CLI，并返回真实入口的最终消息"""
        stream.extend(events)
        return cli.run_cli(
            {"input": "synthetic context", "schema": {}},
            ProviderSettings(),
            {},
            threading.Event(),
            emit,
        )

    return run


@pytest.mark.parametrize("kind", ["item.started", "item.updated", "item.completed"])
@pytest.mark.parametrize(
    "item",
    [
        *(
            {"type": name}
            for name in (
                "command_execution",
                "file_change",
                "web_search",
                "image_generation",
                "collab_tool_call",
            )
        ),
        {"type": "mcp_tool_call", "server": "external", "tool": "read_material"},
        {"type": "mcp_tool_call", "server": "resume_materials", "tool": "exec"},
        {"type": "mcp_tool_call", "server": "resume_materials", "tool": "read_source"},
    ],
)
def test_forbidden_tools_stop_on_every_item_phase(cli_stream, kind, item):
    """外部工具、未知材料工具和未启用的源码工具在更新阶段也必须停止"""
    with pytest.raises(ProviderError, match="不允许|未登记"):
        cli_stream([{"type": kind, "item": item}])


def test_public_progress_hides_details_and_updates_do_not_replace_final_message(cli_stream):
    """材料工具更新可继续，公开进度不包含推理、工具详情或尚未完成的回复"""
    tool = {
        "type": "mcp_tool_call",
        "server": "resume_materials",
        "tool": "read_material",
        "arguments": {"file": "private-arguments"},
        "result": {"text": "private-result"},
    }
    emitted = []
    result = cli_stream(
        [
            {"type": "error", "message": "Reconnecting after stream interrupted"},
            {"type": "item.completed", "item": {"type": "reasoning", "text": "private-reasoning"}},
            *(
                {"type": kind, "item": tool}
                for kind in ("item.started", "item.updated", "item.completed")
            ),
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": '{"reply":"final-result"}'},
            },
            {
                "type": "item.updated",
                "item": {"type": "agent_message", "text": "unfinished-message"},
            },
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 12, "output_tokens": 3, "other": "private-usage"},
            },
        ],
        lambda kind, data: emitted.append((kind, data)),
    )
    assert json.loads(result) == {"reply": "final-result"}
    assert ("usage", {"input_tokens": 12, "output_tokens": 3}) in emitted
    assert sum(kind == "activity" for kind, _ in emitted) == 3
    visible = json.dumps(emitted)
    assert all(
        value not in visible
        for value in (
            "private-arguments",
            "private-result",
            "private-reasoning",
            "final-result",
            "unfinished-message",
            "private-usage",
        )
    )


@pytest.mark.parametrize("kind", ["item.started", "item.updated"])
def test_unfinished_message_cannot_be_published(cli_stream, kind):
    """只有开始或更新消息时，即使轮次完成也不能采用中间 JSON"""
    with pytest.raises(ProviderError, match="未返回完整结果"):
        cli_stream(
            [
                {"type": kind, "item": {"type": "agent_message", "text": '{"reply":"partial"}'}},
                {"type": "turn.completed"},
            ]
        )


@pytest.mark.parametrize("structured_error", [False, True])
def test_failed_turn_keeps_safe_diagnostic_and_rejects_intermediate_json(
    cli_stream, structured_error
):
    """有效中间结果及迟到完成事件不能掩盖失败，报错保留原因并遮盖凭据"""
    reason = "transport unavailable synthetic-cli-key api_key=another-secret"
    with pytest.raises(ProviderError, match="transport unavailable") as caught:
        cli_stream(
            [
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": '{"reply":"partial"}'},
                },
                {
                    "type": "turn.failed",
                    "error": {"message": reason} if structured_error else reason,
                },
                {"type": "turn.completed"},
            ]
        )
    assert "synthetic-cli-key" not in str(caught.value)
    assert "another-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "reason",
    [
        "",
        "Invalid model catalog: missing slug; synthetic-cli-key; api_key=another-secret",
        "x" * 3000 + "\nInvalid model catalog: missing slug; synthetic-cli-key",
    ],
)
def test_startup_failure_drains_stderr_after_input_pipe_closes(tmp_path, reason):
    """真实子进程不读取大段输入就退出，主线程仍返回安全诊断且回收管道"""
    command = [
        sys.executable,
        "-c",
        "import sys; sys.stderr.write(sys.argv[1]); sys.exit(2)",
        reason,
    ]
    with pytest.raises(ProviderError) as caught:
        execute(
            command,
            cwd=tmp_path,
            env={**os.environ, "OPENAI_API_KEY": "synthetic-cli-key"},
            timeout=15,
            cancelled=threading.Event(),
            stdin="x" * (8 * 1024 * 1024),
        )
    message = str(caught.value)
    assert "CLI 或隔离检查失败" in message
    if reason:
        assert "Invalid model catalog: missing slug" in message
    assert "synthetic-cli-key" not in message and "another-secret" not in message
    assert len(message) < 2200


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
    """去包装不能吞掉块外结构化数据、多个结果或截断内容"""
    with pytest.raises(ValueError):
        json.loads(structured_text(message))


@pytest.mark.parametrize(
    "prefix,suffix", [("说明如下：\n", ""), ("", "\n映射完成。"), ("已检查 `n1`。\n", "\n结束。")]
)
def test_unique_json_fence_allows_prose_wrapper(prefix, suffix):
    """唯一完整代码块可以忽略非数据说明，字段和节点仍须通过同一严格模型校验"""
    assert json.loads(structured_text(prefix + '```json\n{"x":1}\n```' + suffix)) == {"x": 1}
