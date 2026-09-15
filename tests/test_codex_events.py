"""校验 Codex 公开动态不会混入推理、命令参数和最终映射。"""

import json
import threading
from io import StringIO

from resume_maker.domain.models import ProviderSettings
from resume_maker.domain.templates import TemplatePlan
from resume_maker.integrations.providers.codex import CodexProvider


def test_public_events_and_resumed_schema(monkeypatch, tmp_path):
    """模拟 CLI 事件，保留会话和用量，同时只向界面发布公开摘要。"""
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
            "item": {"type": "agent_message", "text": plan.model_dump_json()},
        },
        {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}},
    ]
    commands = []

    class Process:
        """以可读取流替代真实 CLI，不触发外部模型。"""

        def __init__(self, command, **kwargs):
            """记录命令并准备模拟输出及空错误流。"""
            commands.append(command)
            self.stdin = StringIO()
            self.stdout = StringIO("\n".join(json.dumps(event) for event in events) + "\n")
            self.stderr = StringIO()

        def wait(self, timeout):
            """模拟进程正常结束。"""
            return 0

        def poll(self):
            """避免测试触发真实进程回收。"""
            return 0

    monkeypatch.setattr("resume_maker.integrations.providers.codex.subprocess.Popen", Process)
    monkeypatch.setattr(CodexProvider, "executable", lambda *_: "codex")
    emitted = []
    result = CodexProvider().run_structured(
        result_model=TemplatePlan,
        workspace=tmp_path,
        prompt="测试",
        thread_id="own-session",
        settings=ProviderSettings(model="test-model", reasoning_effort="medium", profile="test"),
        cancelled=threading.Event(),
        emit=lambda kind, data: emitted.append((kind, data)),
    )
    assert result == plan
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
