"""统一系统日志的可观测行为、隔离和有界读取回归"""

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from test_jobs import FakeProvider, wait_job

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.infrastructure.activity import MAX_DETAIL, ActivityLog
from resume_maker.infrastructure.database import now, uid
from resume_maker.infrastructure.observability import activity_scope, record


def test_http_activity_captures_success_denial_validation_and_exceptions(tmp_path):
    """所有业务 API 状态可定位到请求，读取日志本身不增加新记录"""
    app = create_app(Config(data_dir=tmp_path, token="instance-secret"))

    @app.get("/api/test-crash")
    def crash():
        """构造未捕获异常以验证服务故障不会遗漏"""
        raise RuntimeError("synthetic failure")

    with TestClient(app, raise_server_exceptions=False) as client:
        headers = {"x-resume-token": "instance-secret"}
        response = client.get(
            "/api/state?api_key=encoded%2Dcanary&tag=one&tag=two", headers=headers
        )
        assert response.status_code == 200
        trace = response.headers["x-request-id"]
        assert client.get("/api/state").status_code == 401
        assert (
            client.get(
                "/api/state", headers={**headers, "origin": "https://example.invalid"}
            ).status_code
            == 403
        )
        assert client.post("/api/projects", json={}, headers=headers).status_code == 422
        assert client.get("/api/test-crash", headers=headers).status_code == 500
        assert client.get("/api/activity").status_code == 401
        first = client.get("/api/activity", headers=headers).json()
        second = client.get("/api/activity", headers=headers).json()
        assert first["cursor"] == second["cursor"]
        assert not first["write_failures"]
        related = client.get("/api/activity", params={"trace_id": trace}, headers=headers).json()
        assert {event["category"] for event in related["events"]} >= {"api", "service"}
        request_event = next(event for event in related["events"] if event["event"] == "request")
        request_detail = app.state.services.db.activity.detail(request_event["id"])
        assert request_detail["payload"]["query"]["tag"] == ["one", "two"]
        responses = [
            app.state.services.db.activity.detail(event["id"])
            for event in first["events"]
            if event["event"] == "response"
        ]
        assert {event["payload"]["status"] for event in responses} >= {200, 401, 403, 422, 500}
        crash_event = next(event for event in responses if event["payload"]["status"] == 500)
        assert "synthetic failure" in crash_event["payload"]["error"]["traceback"]
        assert all(event["duration_ms"] >= 0 for event in responses)
        exported = client.get("/api/activity/export", headers=headers)
        assert exported.status_code == 200 and "instance-secret" not in exported.text
        assert "encoded-canary" not in exported.text
        assert all(json.loads(line)["id"] for line in exported.text.splitlines())


def test_activity_cursor_filter_search_export_and_restart(tmp_path):
    """分页和筛选在新事件插入后不漏条，字面搜索及重启后详情保持一致"""
    path = tmp_path / "activity.sqlite"
    log = ActivityLog(path)
    for number in range(6):
        log.write(
            "tool" if number % 2 else "api", "done", f"event-{number}", {"text": "100%_literal"}
        )
    latest = log.page(limit=2)
    first_increment = log.page(after=0, limit=2)
    assert [event["id"] for event in first_increment["events"]] == [1, 2]
    assert first_increment["cursor"] == 2 and first_increment["has_more"]
    assert [event["id"] for event in latest["events"]] == [5, 6]
    older = log.page(before=latest["oldest"], limit=2)
    assert [event["id"] for event in older["events"]] == [3, 4]
    log.write("tool", "done", "new")
    incremental = log.page(after=2, limit=2)
    assert incremental["cursor"] == 4 and incremental["has_more"]
    assert [event["id"] for event in log.page(after=incremental["cursor"])["events"]] == [5, 6, 7]
    empty = log.page(after=6, category="ai")
    assert empty["cursor"] == 7 and not empty["events"]
    assert log.page(q="%_")["total"] == 6
    assert log.page(q="not-present")["total"] == 0
    exported = [json.loads(line) for line in log.export(category="tool")]
    assert len(exported) == 4 and all(row["category"] == "tool" for row in exported)
    restarted = ActivityLog(path)
    assert restarted.detail(5)["title"] == "event-4"


def test_successful_polling_filter_preserves_failures_and_raw_trace(tmp_path):
    """默认路径只隐藏成功 GET 的普通轨迹，错误请求和关联详情仍可查看"""
    app = create_app(Config(data_dir=tmp_path, token="synthetic-token"))
    with TestClient(app) as client:
        headers = {"x-resume-token": "synthetic-token"}
        success = client.get("/api/state", headers=headers)
        client.get("/api/state")
        client.get("/api/missing", headers=headers)
        client.get("/api/template-library", headers=headers)
        query = {"hide_polling": True}
        filtered = client.get("/api/activity", params=query, headers=headers).json()
        assert not any(
            row["trace_id"] == success.headers["x-request-id"] for row in filtered["events"]
        )
        titles = [row["title"] for row in filtered["events"]]
        assert "GET /api/state · 401" in titles
        assert "GET /api/missing · 404" in titles
        assert "GET /api/template-library · 200" in titles
        exported = client.get("/api/activity/export", params=query, headers=headers)
        assert [json.loads(line)["id"] for line in exported.text.splitlines()] == [
            row["id"] for row in filtered["events"]
        ]
        related = client.get(
            "/api/activity",
            params={**query, "trace_id": success.headers["x-request-id"]},
            headers=headers,
        ).json()
        assert len(related["events"]) == 4
        raw = client.get("/api/activity", headers=headers).json()
        assert raw["total"] == filtered["total"] + 4
        assert (
            client.get(
                "/api/activity", params={**query, "polling_paths": ""}, headers=headers
            ).json()["total"]
            == raw["total"]
        )


def test_polling_live_retraction_pagination_and_path_rules(tmp_path):
    """跨轮询批次撤回先到的开始事件，分页计数和导出保持同一过滤语义"""
    log = ActivityLog(tmp_path / "log.sqlite")
    log.write("api", "request", "GET /api/state", trace_id="pending")
    log.write("service", "started", "workspace.state", trace_id="pending")
    first = log.page(hide_polling=True)
    assert len(first["events"]) == 2
    log.write("api", "response", "GET /api/state · 200", trace_id="pending")
    # 相同链路上的警告和 AI、工具活动不能被过滤规则吞掉
    for category, level in [
        ("service", "warning"),
        ("api", "error"),
        ("ai", "info"),
        ("tool", "info"),
    ]:
        log.write(category, "done", "keep", trace_id="pending", level=level)
    incremental = log.page(after=first["cursor"], hide_polling=True, limit=1)
    assert incremental["hidden_trace_ids"] == ["pending"]
    assert incremental["total"] == 4 and incremental["has_more"]
    found = incremental["events"]
    while incremental["has_more"]:
        incremental = log.page(after=incremental["cursor"], hide_polling=True, limit=1)
        found += incremental["events"]
    assert [row["id"] for row in found] == [4, 5, 6, 7]
    assert len(list(log.export(hide_polling=True))) == 4
    assert log.page(hide_polling=True, q="workspace.state")["total"] == 0
    assert log.page(hide_polling=True, category="service")["counts"] == {"service": 1}
    assert len(log.page(hide_polling=True, before=6)["events"]) == 2
    log.write("api", "response", "GET /api/templates/analyses/one/progress · 200", trace_id="wild")
    log.write("api", "response", "POST /api/state · 200", trace_id="post")
    log.write("api", "response", "GET /api/state · 201", trace_id="created")
    log.write("api", "response", "GET /api/state_extra · 200", trace_id="literal")
    assert log.page(hide_polling=True)["total"] == 7
    assert log.page(hide_polling=True, polling_paths="/api/state%extra")["total"] == 11
    assert log.page(hide_polling=True, polling_paths="/api/state_*")["total"] == 10
    # 只有被过滤的响应到达时也要推进游标并撤回已显示记录
    cursor = log.page()["cursor"]
    log.write("api", "response", "GET /api/state · 200", trace_id="last")
    empty = log.page(after=cursor, hide_polling=True)
    assert empty["events"] == [] and empty["cursor"] == cursor + 1
    assert empty["hidden_trace_ids"] == ["last"]


def test_filtered_export_keeps_snapshot_when_stream_worker_changes(tmp_path):
    """流式下载跨工作线程仍可继续，晚到的响应不改变导出中的过滤快照"""
    log = ActivityLog(tmp_path / "log.sqlite")
    for index in range(201):
        log.write("system", "done", f"event-{index}")
    log.write("api", "request", "GET /api/state", trace_id="pending")
    log.write("service", "started", "workspace.state", trace_id="pending")
    stream = log.export(hide_polling=True)
    with ThreadPoolExecutor(max_workers=1) as first, ThreadPoolExecutor(max_workers=1) as second:
        head = first.submit(next, stream).result()
        log.write("api", "response", "GET /api/state · 200", trace_id="pending")
        rest = second.submit(list, stream).result()
    exported = [json.loads(line) for line in [head, *rest]]
    assert len(exported) == 203
    assert exported[-1]["title"] == "workspace.state"
    assert log.page(hide_polling=True)["total"] == 201


def test_sensitive_values_binary_and_large_details_are_bounded(tmp_path):
    """嵌套密钥、文本鉴权、编码查询和大型内容不泄漏到列表详情及导出"""
    log = ActivityLog(tmp_path / "log.sqlite")
    log.write(
        "ai",
        "message",
        "Bearer bearer-canary",
        {
            "nested": {"api_key": "key-canary", "password": "password-canary"},
            "text": 'Authorization: Bearer header-canary\napi_key="key with spaces"\n'
            "https://name:password-in-url@example.invalid/\n"
            '"token": "token-canary"',
            "bytes": b"BINARY-CANARY",
            "usage": {"input_tokens": 124},
        },
    )
    text = "".join(log.export())
    for secret in (
        "bearer-canary",
        "key-canary",
        "password-canary",
        "header-canary",
        "key with spaces",
        "password-in-url",
        "token-canary",
        "BINARY-CANARY",
    ):
        assert secret not in text
    assert log.detail(1)["payload"]["usage"]["input_tokens"] == 124
    log.write("ai", "context", "large", {"text": "x" * (MAX_DETAIL + 100)})
    assert log.detail(2)["payload"]["_truncated"]
    assert "payload" not in log.page()["events"][0]
    known = ActivityLog(tmp_path / "known.sqlite", secrets=("t", "12345678"))
    known.write("ai", "context", "test", {"text": "12345678", "value": 12345678, "ok": True})
    assert known.detail(1)["payload"] == {"text": "[已遮盖]", "value": 12345678, "ok": True}


def test_job_messages_and_tool_events_share_request_trace(tmp_path):
    """后台模型消息及工具结果保留提交请求、会话和项目的关联"""

    class Provider(FakeProvider):
        """在可控回复前模拟本机 CLI 的工具活动"""

        def run(self, **kwargs):
            """提供确定的工具参数和结果，避免调用真实供应商"""
            record("tool", "item.started", "read_source", {"arguments": {"path": "README.md"}})
            record("tool", "item.completed", "read_source", {"result": "synthetic source"})
            return super().run(**kwargs)

    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("synthetic", encoding="utf-8")
    app = create_app(Config(data_dir=tmp_path / "data", token="synthetic-token"), Provider())
    with TestClient(app) as client:
        catalog = app.state.services.catalog
        project = catalog.create_project("Example", [str(source)])
        conversation = catalog.db.all("SELECT * FROM conversations")[0]
        log = catalog.db.activity
        with activity_scope(log, trace_id="submit-trace"):
            job = app.state.services.jobs.submit(
                conversation["id"], "整理源码", "chat", project["head_revision"], "all", uid()
            )
        assert wait_job(catalog, job["id"])["status"] == "completed"
        app.state.services.jobs.stop()
        events = log.page(job_id=job["id"], limit=500)["events"]
        assert {event["event"] for event in events} >= {
            "user",
            "assistant",
            "item.started",
            "item.completed",
        }
        assert all(event["trace_id"] == "submit-trace" for event in events)
        assert all(event["conversation_id"] == conversation["id"] for event in events)
        assert all(event["project_id"] == project["id"] for event in events)
        headers = {"x-resume-token": "synthetic-token"}
        assert (
            client.post(
                "/api/activity/client",
                headers=headers,
                json={
                    "event": "uncaught_error",
                    "message": "browser failure",
                    "stack": "synthetic stack",
                },
            ).status_code
            == 200
        )
        assert log.page(category="client")["total"] == 1
        app.state.services.conversations.rebuild_conversation(conversation["id"])
        system = log.page(category="ai", conversation_id=conversation["id"], q="重建模型上下文")
        assert any(event["event"] == "system" for event in system["events"])


def test_history_import_is_dated_idempotent_and_survives_message_deletion(
    catalog, project, tmp_path
):
    """补录按原时间排序，重启不重复且后续删除会话不会删除调试记录"""
    conversation = catalog.db.all("SELECT * FROM conversations")[0]
    stamp = now()
    with catalog.db.transaction() as conn:
        conn.execute(
            "INSERT INTO messages VALUES (?,?,NULL,'user',?,?)",
            (uid(), conversation["id"], "旧消息", stamp),
        )
    log = ActivityLog(tmp_path / "activity.sqlite")
    log.import_history(catalog.db)
    log.import_history(catalog.db)
    assert log.page()["total"] == 1
    assert log.detail(1)["created_at"] == stamp
    with catalog.db.transaction() as conn:
        conn.execute("DELETE FROM messages")
    assert log.detail(1)["payload"]["text"] == "旧消息"

    job_id = uid()
    with catalog.db.transaction() as conn:
        conn.execute(
            "INSERT INTO jobs(id,project_id,conversation_id,kind,status,request_json,"
            "created_at,request_key) VALUES (?,?,?,'chat','failed','{}',?,?)",
            (job_id, project["id"], conversation["id"], now(), uid()),
        )
    catalog.db.event(job_id, "error", {"text": "历史工具调用失败"})
    imported = ActivityLog(tmp_path / "historical-error.sqlite")
    imported.import_history(catalog.db)
    assert imported.page(level="error")["events"][0]["job_id"] == job_id


def test_concurrent_instances_retention_and_write_failure(tmp_path, monkeypatch):
    """并发活动不串实例，过期清理保持游标，日志写失败仍允许业务继续"""
    left = ActivityLog(tmp_path / "left.sqlite", max_records=3)
    right = ActivityLog(tmp_path / "right.sqlite")

    def worker(log, label):
        """在线程内建立独立上下文以验证日志不会跨请求混用"""
        with activity_scope(log, trace_id=label):
            for index in range(6):
                record("system", "test", f"{label}-{index}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda pair: worker(*pair), ((left, "left"), (right, "right"))))
    assert [event["id"] for event in left.page()["events"]] == [4, 5, 6]
    assert right.page()["total"] == 6
    assert {event["trace_id"] for event in left.page()["events"]} == {"left"}
    with closing(left.connect()) as conn, conn:
        conn.execute("UPDATE activity SET created_at='2000-01-01T00:00:00.000+00:00'")
    assert ActivityLog(left.path).page()["total"] == 0

    def fail():
        """模拟磁盘故障而不接触真实用户目录"""
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(left, "connect", fail)
    left.write("api", "completed", "business succeeded")
    assert left.write_failures == 1
    assert "disk full" in left.last_error


def test_cli_trace_records_tool_arguments_result_and_agent_message(tmp_path, monkeypatch):
    """CLI 事件完整写入本机轨迹，原进度回调仍保持简要文本协议"""
    from contextlib import contextmanager

    from resume_maker.domain.models import ProviderSettings
    from resume_maker.integrations.providers import cli

    @contextmanager
    def credentials(root, env, flag):
        """测试不访问本机登录信息"""
        yield env

    @contextmanager
    def workspace():
        """事件解析测试仅使用临时材料，真实目录权限由沙箱边界测试覆盖"""
        root = tmp_path / "sandbox"
        (root / "control").mkdir(parents=True)
        (root / "materials").mkdir()
        yield root

    def execute(command, **kwargs):
        """以真实 CLI JSON 结构模拟受限工具调用和回复"""
        if "--version" in command:
            return "codex-cli 0.154.0"
        emit = kwargs["event"]
        item = {
            "id": "call-1",
            "type": "mcp_tool_call",
            "server": "resume_materials",
            "tool": "read_material",
            "arguments": {"file": "context.txt"},
        }
        emit({"type": "item.started", "item": item})
        emit({"type": "item.completed", "item": {**item, "result": {"text": "tool-result"}}})
        emit(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": '{"reply":"hello"}'},
            }
        )
        emit({"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 3}})

    monkeypatch.setattr(cli, "connection", lambda *_: ({}, {}))
    monkeypatch.setattr(cli, "workspace", workspace)
    monkeypatch.setattr(cli, "isolated_credentials", credentials)
    monkeypatch.setattr(cli, "native_executable", lambda *_: "synthetic-cli")
    monkeypatch.setattr(cli, "write_catalog", lambda root, selected: str(root / "catalog.json"))
    monkeypatch.setattr(cli, "execute", execute)
    log = ActivityLog(tmp_path / "log.sqlite")
    with activity_scope(log, trace_id="cli-test"):
        reply = cli.run_cli(
            {"input": "synthetic context", "schema": {}},
            ProviderSettings(),
            {},
            threading.Event(),
            lambda *_: None,
        )
    assert json.loads(reply)["reply"] == "hello"
    events = [json.loads(line) for line in log.export(category="tool")]
    assert len(events) == 2
    assert events[0]["payload"]["item"]["arguments"]["file"] == "context.txt"
    assert events[1]["payload"]["item"]["result"]["text"] == "tool-result"
    assert log.page(category="ai", q="hello")["total"] == 1


@pytest.mark.parametrize("params", [{"limit": 501}, {"after": -1}, {"q": "x" * 501}])
def test_log_query_limits_are_enforced(tmp_path, params):
    """拒绝无界日志查询，避免浏览器误操作读取全部详情"""
    app = create_app(Config(data_dir=tmp_path, token="synthetic-token"))
    with TestClient(app) as client:
        response = client.get(
            "/api/activity", params=params, headers={"x-resume-token": "synthetic-token"}
        )
        assert response.status_code == 422
