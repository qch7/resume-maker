"""验证只读工具的目录边界、进程回收和真实 CLI 的工具注册结果"""

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psutil
import pytest

from resume_maker.domain.models import ProviderSettings
from resume_maker.integrations.providers.base import Cancelled
from resume_maker.integrations.providers.cli import run_cli
from resume_maker.integrations.providers.credentials import isolated_credentials
from resume_maker.integrations.providers.material_server import call, dispatch
from resume_maker.integrations.providers.process import execute
from resume_maker.integrations.providers.sandbox import materials


def test_material_boundaries_and_line_numbers(tmp_path):
    """仅生成的文件编号可读，路径穿越、命令、凭据文件和链接全部被拒绝"""
    root = tmp_path / "materials"
    root.mkdir()
    (tmp_path / "original.txt").write_text("PRIVATE-CANARY", encoding="utf-8")
    materials(
        tmp_path,
        "Analyze\n"
        + json.dumps(
            {
                "source_materials": {
                    "files": [
                        {"source": "source-0", "path": "src/test.py", "text": "first\nneedle\nlast"}
                    ]
                }
            }
        ),
        {},
    )
    rows = json.loads(call(root, "read_material", {"file": "source-0001.txt", "start_line": 2}))
    assert rows == [{"line": 2, "text": "needle"}, {"line": 3, "text": "last"}]
    assert json.loads(call(root, "search_materials", {"query": "needle"}))[0]["line"] == 2
    for name in (
        "../original.txt",
        str(tmp_path / "original.txt"),
        "auth.json",
        "source-0001.txt:secret",
        "context.txt/../original.txt",
        "file:///etc/passwd",
    ):
        reply = dispatch(
            root,
            {
                "method": "tools/call",
                "params": {"name": "read_material", "arguments": {"file": name}},
            },
        )
        assert reply["isError"] and "PRIVATE-CANARY" not in str(reply)
    with pytest.raises(ValueError):
        call(root, "exec_command", {"cmd": "anything"})
    os.link(tmp_path / "original.txt", root / "source-0002.txt")
    with pytest.raises(ValueError):
        call(root, "read_material", {"file": "source-0002.txt"})


def test_mcp_stdio_protocol(tmp_path):
    """从真实独立进程验证只读 MCP 能完成初始化、读取和未知工具拒绝"""
    from resume_maker.integrations.providers import material_server

    (tmp_path / "context.txt").write_text("safe material", encoding="utf-8")
    messages = [
        {"id": 1, "method": "initialize"},
        {"id": 2, "method": "tools/list"},
        {
            "id": 3,
            "method": "tools/call",
            "params": {"name": "read_material", "arguments": {"file": "context.txt"}},
        },
        {"id": 4, "method": "tools/call", "params": {"name": "write_file", "arguments": {}}},
    ]
    result = subprocess.run(
        [sys.executable, "-I", material_server.__file__, str(tmp_path)],
        input="\n".join(json.dumps(row) for row in messages) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=15,
    )
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert "safe material" in str(replies[2])
    assert replies[3]["result"]["isError"]


def test_credentials_copy_refresh_and_concurrent_change(tmp_path):
    """只复制鉴权并回存刷新结果，其他 CLI 的新凭据不被覆盖"""
    home, root = tmp_path / "home", tmp_path / "task"
    home.mkdir()
    (root / "control").mkdir(parents=True)
    auth = home / "auth.json"
    auth.write_text('{"token":"old"}', encoding="utf-8")
    (home / "config.toml").write_text("untrusted-config", encoding="utf-8")
    with isolated_credentials(root, {"CODEX_HOME": str(home)}, threading.Event()) as env:
        isolated = Path(env["CODEX_HOME"])
        assert not (isolated / "config.toml").exists()
        (isolated / "auth.json").write_text('{"token":"refreshed"}', encoding="utf-8")
    assert json.loads(auth.read_text())["token"] == "refreshed"
    (root / "control/codex-home/auth.json").unlink()
    (root / "control/codex-home").rmdir()
    with isolated_credentials(root, {"CODEX_HOME": str(home)}, threading.Event()) as env:
        (Path(env["CODEX_HOME"]) / "auth.json").write_text('{"token":"stale"}', encoding="utf-8")
        auth.write_text('{"token":"concurrent"}', encoding="utf-8")
    assert json.loads(auth.read_text())["token"] == "concurrent"


def test_cancel_reaps_child_even_after_leader_exit(tmp_path):
    """管道被后代继承时，取消仍终止全部子进程且及时返回"""
    pidfile = tmp_path / "child.pid"
    script = (
        "import subprocess,sys,pathlib; p=subprocess.Popen([sys.executable,'-c',"
        "'import time; time.sleep(60)']); pathlib.Path(sys.argv[1]).write_text(str(p.pid))"
    )
    flag = threading.Event()

    def cancel():
        """等到后代创建后再触发取消，以覆盖主进程已经退出的情况"""
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        flag.set()

    thread = threading.Thread(target=cancel)
    thread.start()
    try:
        with pytest.raises(Cancelled):
            execute(
                [sys.executable, "-c", script, str(pidfile)],
                cwd=tmp_path,
                env=os.environ.copy(),
                timeout=10,
                cancelled=flag,
            )
    finally:
        thread.join(timeout=6)
    pid = int(pidfile.read_text())
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE


@pytest.mark.skipif(
    os.environ.get("RESUME_MAKER_TEST_NATIVE_CLI") != "1",
    reason="显式启用后使用真实 CLI 连接本机合成服务，不访问供应商",
)
def test_native_cli_tool_boundary(tmp_path):
    """以本机假模型验证禁用 shell、正确读取副本、拒绝穿越和配置污染"""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        """仅返回合成工具调用的本机 Responses 服务"""

        def log_message(self, *args):
            """测试不输出请求或鉴权日志"""

        def do_POST(self):
            """先尝试 shell 和越界读取，再返回固定结构结果"""
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            number = len(requests)
            if number < 4:
                item = {
                    "id": f"fc_{number}",
                    "type": "function_call",
                    "call_id": f"call_{number}",
                    "name": "exec_command" if number == 1 else "read_material",
                    "arguments": json.dumps(
                        {"cmd": "echo SHOULD_NOT_RUN"}
                        if number == 1
                        else {"file": "context.txt" if number == 2 else "../control/auth.json"}
                    ),
                }
                if number > 1:
                    item["namespace"] = "mcp__resume_materials"
            else:
                item = {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": '{"answer":"done"}', "annotations": []}
                    ],
                }
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            events = [
                ("response.created", {"response": {"id": "resp_1", "status": "in_progress"}}),
                ("response.output_item.done", {"output_index": 0, "item": item}),
                (
                    "response.completed",
                    {
                        "response": {
                            "id": "resp_1",
                            "status": "completed",
                            "output": [item],
                            "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
                        }
                    },
                ),
            ]
            for name, value in events:
                self.wfile.write(
                    (
                        "event: " + name + "\ndata: " + json.dumps({"type": name, **value}) + "\n\n"
                    ).encode()
                )
                self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    (tmp_path / "AGENTS.md").write_text("RULES-CANARY", encoding="utf-8")
    (tmp_path / "config.toml").write_text(
        'model="test-model"\nmodel_provider="test"\ndeveloper_instructions="CONFIG-CANARY"\n'
        '[mcp_servers.untrusted]\ncommand="SHOULD-NOT-START"\n'
        '[model_providers.test]\nname="test"\nwire_api="responses"\nenv_key="SYNTHETIC_KEY"\n'
        f'base_url="http://127.0.0.1:{server.server_port}/v1"\n',
        encoding="utf-8",
    )
    try:
        result = run_cli(
            {
                "input": "SAFE-MATERIAL",
                "schema": {
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                    "additionalProperties": False,
                },
            },
            ProviderSettings(timeout_seconds=30),
            {"CODEX_HOME": str(tmp_path), "SYNTHETIC_KEY": "SECRET-CANARY"},
            threading.Event(),
            lambda *_: None,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert json.loads(result) == {"answer": "done"}
    wire = json.dumps(requests, ensure_ascii=False)
    assert all(value not in wire for value in ("CONFIG-CANARY", "RULES-CANARY", "SECRET-CANARY"))
    assert "unsupported call: exec_command" in wire
    assert "读取被拒绝" in wire
    assert any(
        "SAFE-MATERIAL" in str(item.get("output", ""))
        for req in requests
        for item in req["input"]
        if item["type"] == "function_call_output"
    )
    for request in requests:
        assert {item["name"] for item in request["tools"]} <= {
            "mcp__resume_materials",
            "list_mcp_resources",
            "list_mcp_resource_templates",
            "read_mcp_resource",
            "request_user_input",
        }
