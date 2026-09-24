"""验证只读工具的目录边界、进程回收和真实 CLI 的工具注册结果"""

import base64
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
from test_privacy_mosaic import synthetic_image

from resume_maker.domain.models import Model, ProviderSettings
from resume_maker.integrations.providers import sandbox
from resume_maker.integrations.providers.base import Cancelled, MosaicImage, ProviderError
from resume_maker.integrations.providers.cli import run_cli
from resume_maker.integrations.providers.codex import CodexProvider
from resume_maker.integrations.providers.credentials import isolated_credentials
from resume_maker.integrations.providers.material_server import call, dispatch
from resume_maker.integrations.providers.mosaic import mosaic_sheets
from resume_maker.integrations.providers.process import execute
from resume_maker.integrations.providers.sandbox import materials, posix_parent


class BoundaryReply(Model):
    """真实 CLI 边界验收所用的最小输出契约"""

    answer: str


@pytest.mark.parametrize("exit_reason", ["success", "failure", "cancelled"])
def test_project_sandbox_cleans_only_its_task(tmp_path, monkeypatch, exit_reason):
    """项目内沙箱在成功、异常和取消后清理本轮副本，保留源码及其他任务"""
    project = tmp_path / "project"
    project.mkdir()
    original = project / "main.py"
    original.write_text("ORIGINAL-CANARY", encoding="utf-8")
    parent = project / "ResumeMakerSandbox"
    parent.mkdir(mode=0o700)
    other = parent / "task-other"
    other.mkdir()
    marker = other / "context.txt"
    marker.write_text("OTHER-TASK-CANARY", encoding="utf-8")
    monkeypatch.setattr(sandbox, "sandbox_directory", lambda: parent)
    monkeypatch.chdir(tmp_path)
    try:
        with sandbox.workspace() as root:
            assert root.parent == parent and root != other
            assert (root / "materials").is_dir() and (root / "control").is_dir()
            (root / "control" / "private.txt").write_text("PRIVATE-CANARY", encoding="utf-8")
            if exit_reason == "failure":
                raise RuntimeError("合成任务失败")
            if exit_reason == "cancelled":
                raise Cancelled("合成任务取消")
    except (RuntimeError, Cancelled):
        assert exit_reason != "success"
    assert not root.exists()
    assert list(parent.iterdir()) == [other]
    assert original.read_text(encoding="utf-8") == "ORIGINAL-CANARY"
    assert marker.read_text(encoding="utf-8") == "OTHER-TASK-CANARY"


@pytest.mark.skipif(os.name == "nt", reason="POSIX 所有权及权限由 Linux CI 验证")
@pytest.mark.parametrize("mode", [0o700, 0o755, 0o770, 0o777])
def test_posix_parent_requires_private_permissions(tmp_path, monkeypatch, mode):
    """现有沙箱父目录只有当前账户私有权限可用，拒绝时不改动目录"""
    parent = tmp_path / "sandbox"
    parent.mkdir(mode=mode)
    parent.chmod(mode)
    monkeypatch.setattr(sandbox, "sandbox_directory", lambda: parent)
    if mode == 0o700:
        with sandbox.workspace() as root:
            assert root.parent == parent and (root / "control").is_dir()
            assert root.stat().st_mode & 0o777 == 0o700
    else:
        with pytest.raises(ProviderError, match="0700"), sandbox.workspace():
            pytest.fail("权限过宽时不得创建任务目录")
    assert parent.stat().st_mode & 0o777 == mode
    assert list(parent.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX 所有权及链接由 Linux CI 验证")
def test_posix_parent_rejects_foreign_owner_files_and_links(tmp_path, monkeypatch):
    """即使权限私有也拒绝其他账户的目录，文件和符号链接同样不能充当父目录"""
    parent = tmp_path / "sandbox"
    parent.mkdir(mode=0o700)
    file = tmp_path / "file"
    file.write_text("synthetic")
    link = tmp_path / "link"
    link.symlink_to(parent, target_is_directory=True)
    for path in (file, link):
        with pytest.raises(ProviderError, match="普通目录"):
            posix_parent(path)
    monkeypatch.setattr(os, "geteuid", lambda: parent.stat().st_uid + 1)
    with pytest.raises(ProviderError, match="不属于当前账户"):
        posix_parent(parent)


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_material_boundaries_and_line_numbers(tmp_path, newline):
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
                        {
                            "source": "source-0",
                            "path": "src/test.py",
                            "text": newline.join(["first", "needle", "last"]),
                        }
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
    try:
        assert psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        # 查询期间退出的进程同样已完成回收
        pass


@pytest.mark.skipif(os.name != "nt", reason="Windows 进程挂起和 Job Object 边界")
def test_fast_exit_waits_for_job_assignment(tmp_path, monkeypatch):
    """模拟繁忙机器延迟绑定任务对象，快速退出命令仍正常完成且不逃逸"""
    from resume_maker.integrations.providers import process as module

    original = module.windows_job

    def delayed(process):
        """让子进程获得足够时间以暴露未挂起启动的退出竞态"""
        time.sleep(0.2)
        return original(process)

    monkeypatch.setattr(module, "windows_job", delayed)
    result = execute(
        [sys.executable, "-c", "print('FAST-COMPLETED')"],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout=5,
        cancelled=threading.Event(),
    )
    assert result.strip() == "FAST-COMPLETED"


@pytest.mark.skipif(
    os.environ.get("RESUME_MAKER_TEST_NATIVE_CLI") != "1",
    reason="显式启用后使用真实 CLI 连接本机合成服务，不访问供应商",
)
@pytest.mark.parametrize("model", ["test-model", "gpt-5.5", "gpt-6-astra"])
@pytest.mark.parametrize("with_mosaic", [False, True])
def test_native_cli_tool_boundary(tmp_path, model, with_mosaic):
    """真实 CLI 按需读取大文件尾部并还原新身份值，同时拒绝越界及配置污染"""
    requests = []
    raw_image = synthetic_image()
    images = [MosaicImage("n71", raw_image)] if with_mosaic else []
    root = tmp_path / "PRIVATE-SOURCE-ROOT"
    root.mkdir()
    tail = "TAIL_FEATURE late4726@example.invalid 762810219043785"
    original = "# ordinary source\n" * 12000 + tail + "\n"
    (root / "main.py").write_text(original, encoding="utf-8")
    (root / "feature.py").write_text("SEARCH_FEATURE", encoding="utf-8")
    (root / ".env").write_text("SOURCE-SECRET-CANARY", encoding="utf-8")
    calls = [
        ("exec_command", {"cmd": "echo SHOULD_NOT_RUN"}),
        ("apply_patch", {"patch": "SHOULD_NOT_RUN"}),
        ("read_material", {"file": "context.txt"}),
        ("read_material", {"file": "../control/auth.json"}),
        ("list_source_files", {}),
        ("search_sources", {"query": "SEARCH_FEATURE", "glob": "feature.py"}),
        ("read_source", {"source": "source-0", "path": "main.py", "start_line": 12001}),
        ("read_source", {"source": "source-0", "path": "../config.toml"}),
        ("read_source", {"source": "source-0", "path": ".env"}),
        ("read_material", {"file": "../control/source-access.json"}),
    ]

    class Handler(BaseHTTPRequestHandler):
        """仅返回合成工具调用的本机 Responses 服务"""

        def log_message(self, *args):
            """测试不输出请求或鉴权日志"""

        def do_POST(self):
            """先尝试 shell 和越界读取，再返回固定结构结果"""
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            number = len(requests)
            if number <= len(calls):
                item = {
                    "id": f"fc_{number}",
                    "type": "function_call",
                    "call_id": f"call_{number}",
                    "name": calls[number - 1][0],
                    "arguments": json.dumps(calls[number - 1][1]),
                }
                if number > 2:
                    item["namespace"] = "mcp__resume_materials"
            else:
                output = next(
                    item["output"]
                    for item in payload["input"]
                    if item.get("call_id") == "call_7" and item["type"] == "function_call_output"
                )
                content = json.loads(output) if isinstance(output, str) else output
                answer = json.dumps(content, ensure_ascii=False)
                for block in content:
                    try:
                        answer = json.loads(block.get("text", ""))["lines"][0]["text"]
                        break
                    except (ValueError, KeyError):
                        continue
                item = {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({"answer": answer}),
                            "annotations": [],
                        }
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
        f'model="{model}"\nmodel_provider="test"\ndeveloper_instructions="CONFIG-CANARY"\n'
        '[mcp_servers.untrusted]\ncommand="SHOULD-NOT-START"\n'
        '[model_providers.test]\nname="test"\nwire_api="responses"\nenv_key="SYNTHETIC_KEY"\n'
        f'base_url="http://127.0.0.1:{server.server_port}/v1"\n'
        '[profiles."团队 profile.v2"]\nmodel_reasoning_effort="none"\n',
        encoding="utf-8",
    )
    try:
        provider = CodexProvider(
            environment={"CODEX_HOME": str(tmp_path), "SYNTHETIC_KEY": "SECRET-CANARY"},
            runner=run_cli,
        ).with_private_data({"personal": {"name": "合成测试甲", "age": "21"}})
        result = provider.run_structured(
            result_model=BoundaryReply,
            workspace=tmp_path,
            prompt="SAFE-MATERIAL\n姓名：合成测试甲\n电话：13800004726\n"
            "邮箱：synthetic4726@example.invalid\n颁发单位\n合成测试委员会",
            thread_id="PRIVATE-OLD-SESSION",
            settings=ProviderSettings(
                timeout_seconds=60, profile="团队 profile.v2" if with_mosaic else ""
            ),
            cancelled=threading.Event(),
            emit=lambda *_: None,
            images=images,
            sources=[{"id": "source-0", "path": str(root)}],
            data_dir=tmp_path / "data",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert result.answer == tail
    assert (root / "main.py").read_text(encoding="utf-8") == original
    wire = json.dumps(requests, ensure_ascii=False)
    attached = [
        block["image_url"]
        for item in requests[0]["input"]
        if item.get("type") == "message"
        for block in item.get("content", [])
        if block.get("type") == "input_image"
    ]
    assert len(attached) == int(with_mosaic)
    if with_mosaic:
        expected, _ = mosaic_sheets(images, threading.Event())
        assert base64.b64decode(attached[0].partition(",")[2]) == expected[0]
    assert base64.b64encode(raw_image).decode() not in wire
    assert all(value not in wire for value in ("CONFIG-CANARY", "RULES-CANARY", "SECRET-CANARY"))
    assert all(
        value not in wire
        for value in (
            "合成测试甲",
            "13800004726",
            "synthetic4726@example.invalid",
            "合成测试委员会",
            "PRIVATE-OLD-SESSION",
            "PRIVATE-SOURCE-ROOT",
            "SOURCE-SECRET-CANARY",
            "late4726@example.invalid",
            "762810219043785",
            "7628102",
            "9043785",
        )
    )
    assert "[[RM_" in wire
    assert "unsupported call: exec_command" in wire
    assert "unsupported call: apply_patch" in wire
    assert "读取被拒绝" in wire
    assert "SEARCH_FEATURE" in wire and "main.py" in wire
    assert any(
        "SAFE-MATERIAL" in str(item.get("output", ""))
        for req in requests
        for item in req["input"]
        if item["type"] == "function_call_output"
    )
    for request in requests:
        assert request["model"] == model
        if with_mosaic:
            assert request["reasoning"]["effort"] == "none"
        assert {item["name"] for item in request["tools"]} <= {
            "mcp__resume_materials",
            "list_mcp_resources",
            "list_mcp_resource_templates",
            "read_mcp_resource",
            "request_user_input",
        }
