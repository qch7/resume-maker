"""验证采集配置真正控制落盘，并在重启、历史补录和故障后保持一致"""

import json
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.domain.activity import ACTIVITY_CATEGORIES, ActivityCaptureSettings
from resume_maker.infrastructure.activity import ActivityLog
from resume_maker.infrastructure.database import now, uid
from resume_maker.plugin_packages.sys_activity.services.activity import (
    capture_settings,
    save_capture_settings,
)


def test_default_capture_skips_disabled_categories_before_serialization(tmp_path, monkeypatch):
    """默认仅 AI 落盘，其他类别的警告和错误也不打开数据库或序列化正文"""
    log = ActivityLog(tmp_path / "activity.sqlite")
    assert capture_settings(log).categories == ["ai"]
    assert log.write("ai", "assistant", "保留回复", {"text": "合成内容"})

    def unexpected(*args, **kwargs):
        """关闭类别不应触发数据库访问或大型正文序列化"""
        pytest.fail("未采集类别仍在处理日志正文或访问数据库")

    with monkeypatch.context() as patch:
        patch.setattr(log, "connect", unexpected)
        patch.setattr("resume_maker.infrastructure.activity.detail_json", unexpected)
        for category in set(ACTIVITY_CATEGORIES) - {"ai"}:
            for level in ("info", "warning", "error"):
                assert log.write(category, "test", "不采集", object(), level=level)
    page = log.page()
    assert page["total"] == page["cursor"] == 1
    assert page["counts"] == {"ai": 1}
    assert page["write_failures"] == 0
    assert log.detail(1)["payload"] == {"text": "合成内容"}


def test_capture_api_applies_immediately_and_survives_restart_and_delete(tmp_path):
    """勾选类别实时影响业务日志，空选停止采集且重启和删除均保留设置"""
    config = Config(data_dir=tmp_path, token="synthetic-token")
    app = create_app(config)
    headers = {"x-resume-token": config.token}
    log = app.state.services.db.activity
    with TestClient(app) as client:
        assert client.get("/api/activity/settings").status_code == 401
        assert client.put("/api/activity/settings", json={"categories": []}).status_code == 401
        assert client.get("/api/activity/settings", headers=headers).json() == {
            "categories": ["ai"],
            "capture_starts": False,
        }
        response = client.get("/api/state", headers=headers)
        assert response.status_code == 200 and response.headers["x-request-id"]
        assert log.page()["total"] == 0
        for categories in (["api", "ai", "tool"], list(ACTIVITY_CATEGORIES), []):
            before = log.page()["cursor"]
            saved = client.put(
                "/api/activity/settings", headers=headers, json={"categories": categories}
            )
            assert saved.status_code == 200 and saved.json() == {
                "categories": categories,
                "capture_starts": False,
            }
            assert client.get("/api/activity/settings", headers=headers).json() == saved.json()
            assert log.page()["cursor"] == before
            client.get("/api/state", headers=headers)
            client.post(
                "/api/activity/client",
                headers=headers,
                json={"event": "error", "message": "合成异常"},
            )
            for category in ACTIVITY_CATEGORIES:
                assert log.write(category, "test", "合成日志")
            events = log.page(after=before)["events"]
            assert {row["category"] for row in events} == set(categories)
            assert capture_settings(ActivityLog(log.path)).categories == categories
        retained = log.page()["total"]
        assert retained > 0
        assert len(list(log.export())) == retained
        assert log.detail(log.page()["cursor"])
        assert (
            client.request(
                "DELETE", "/api/activity", headers=headers, json={"before": None}
            ).status_code
            == 200
        )
        assert capture_settings(ActivityLog(log.path)).categories == []
    restarted = create_app(config)
    assert capture_settings(restarted.state.services.db.activity).categories == []
    assert restarted.state.services.db.activity.page()["total"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"categories": ["unknown"]},
        {"categories": "ai"},
        {"categories": None},
        {"categories": ["ai"] * 8},
        {"categories": [], "extra": True},
        {"categories": ["ai"], "capture_starts": "false"},
        {"categories": ["ai"], "capture_starts": 1},
        {"categories": ["ai"], "capture_starts": None},
    ],
)
def test_invalid_capture_settings_do_not_change_policy(tmp_path, body):
    """拒绝未知类别和无效请求，保留原采集策略"""
    app = create_app(Config(data_dir=tmp_path, token="synthetic-token"))
    with TestClient(app) as client:
        response = client.put(
            "/api/activity/settings", headers={"x-resume-token": "synthetic-token"}, json=body
        )
        assert response.status_code == 422
        assert capture_settings(app.state.services.db.activity).categories == ["ai"]


def test_capture_save_failure_keeps_previous_policy(tmp_path):
    """磁盘提交失败时接口报错，内存和重启后的采集类别都不改变"""
    app = create_app(Config(data_dir=tmp_path, token="synthetic-token"))
    log = app.state.services.db.activity
    save_capture_settings(
        log, ActivityCaptureSettings(categories=["ai", "tool", "ai"], capture_starts=True)
    )
    with closing(log.connect()) as conn, conn:
        conn.execute(
            "CREATE TRIGGER fail_settings BEFORE INSERT ON metadata "
            "WHEN NEW.key='capture_starts' "
            "BEGIN SELECT RAISE(FAIL, 'synthetic disk failure'); END"
        )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.put(
            "/api/activity/settings",
            headers={"x-resume-token": "synthetic-token"},
            json={"categories": []},
        )
        assert response.status_code == 500
    assert capture_settings(log).categories == ["ai", "tool"]
    assert capture_settings(ActivityLog(log.path)).categories == ["ai", "tool"]
    assert capture_settings(log).capture_starts
    assert capture_settings(ActivityLog(log.path)).capture_starts
    assert log.write("tool", "done", "仍可记录")
    assert log.page()["counts"] == {"tool": 1}


def test_existing_log_without_capture_settings_defaults_to_ai(tmp_path):
    """旧日志库首次启用新策略时保留历史记录，后续只采集 AI"""
    log = ActivityLog(tmp_path / "activity.sqlite")
    save_capture_settings(
        log, ActivityCaptureSettings(categories=list(ACTIVITY_CATEGORIES), capture_starts=True)
    )
    log.write("api", "request", "历史请求")
    with closing(log.connect()) as conn, conn:
        conn.execute("DELETE FROM metadata WHERE key IN ('capture_categories','capture_starts')")
    restarted = ActivityLog(log.path)
    assert capture_settings(restarted).categories == ["ai"]
    assert not capture_settings(restarted).capture_starts
    restarted.write("api", "request", "不保存的新请求")
    restarted.write("ai", "assistant", "新回复")
    assert [json.loads(line)["title"] for line in restarted.export()] == ["历史请求", "新回复"]


def test_start_capture_skips_before_serialization_and_database_access(tmp_path, monkeypatch):
    """默认开始事件在序列化和数据库访问前跳过，结果和错误仍能落盘"""
    log = ActivityLog(tmp_path / "activity.sqlite")
    assert not capture_settings(log).capture_starts

    def unexpected(*args, **kwargs):
        """被关闭的开始事件不应处理正文或访问数据库"""
        pytest.fail("关闭开始事件后仍发生序列化或数据库访问")

    with monkeypatch.context() as patch:
        patch.setattr(log, "connect", unexpected)
        patch.setattr("resume_maker.infrastructure.activity.detail_json", unexpected)
        for event in (
            "request",
            "started",
            "startup",
            "thread.started",
            "turn.started",
            "item.started",
        ):
            for level in ("info", "warning", "error"):
                assert log.write("ai", event, "不采集", object(), level=level)
    assert log.page()["total"] == log.page()["cursor"] == log.write_failures == 0
    log.write("ai", "item.completed", "完成")
    log.write("ai", "failed", "失败", level="error")
    assert [row["title"] for row in log.page()["events"]] == ["完成", "失败"]


def test_start_capture_switch_is_immediate_and_persists_without_showing_starts(tmp_path):
    """真实请求验证采集和显示独立，重启及删除保留开始事件开关"""
    config = Config(data_dir=tmp_path, token="synthetic-token")
    headers = {"x-resume-token": config.token}
    app = create_app(config)
    with TestClient(app) as client:
        log = app.state.services.db.activity
        for capture_starts in (False, True, False, True):
            body = {"categories": ["api"], "capture_starts": capture_starts}
            saved = client.put("/api/activity/settings", headers=headers, json=body)
            assert saved.status_code == 200 and saved.json() == body
            assert capture_settings(ActivityLog(log.path)).capture_starts == capture_starts
            response = client.get("/api/state", headers=headers)
            trace = response.headers["x-request-id"]
            records = log.page(trace_id=trace)["events"]
            assert any(row["event"] == "request" for row in records) == capture_starts
            assert any(row["event"] == "response" for row in records)
            hidden = client.get(
                "/api/activity",
                headers=headers,
                params={"show_starts": False, "q": "/api/state"},
            ).json()
            assert all(row["event"] == "response" for row in hidden["events"])
        client.request("DELETE", "/api/activity", headers=headers, json={"before": None})
    restarted = create_app(config)
    with TestClient(restarted) as client:
        assert client.get("/api/activity/settings", headers=headers).json() == body


def test_start_display_filter_preserves_paging_counts_exports_and_raw_trace(tmp_path):
    """显示开关统一影响列表、搜索和导出，关联请求仍能查看已采集完整链路"""
    log = ActivityLog(tmp_path / "activity.sqlite")
    save_capture_settings(log, ActivityCaptureSettings(categories=["ai"], capture_starts=True))
    starts = ("request", "started", "startup", "thread.started", "turn.started", "item.started")
    ends = ("response", "completed", "shutdown", "item.updated", "item.completed", "failed")
    for event in (*starts, *ends):
        log.write("ai", event, event, trace_id="full")
    query = {"show_starts": False}
    page = log.page(**query, limit=2)
    assert page["total"] == len(ends) and page["counts"] == {"ai": len(ends)}
    records = page["events"]
    while page["has_more"]:
        page = log.page(**query, before=page["oldest"], limit=2)
        records = page["events"] + records
    assert [row["event"] for row in records] == list(ends)
    assert [json.loads(row)["event"] for row in log.export(**query)] == list(ends)
    assert log.page(**query, q="thread.started")["total"] == 0
    assert log.page(**query, trace_id="full")["total"] == len(starts) + len(ends)
    assert log.page(show_starts=True)["total"] == len(starts) + len(ends)


def test_history_import_only_loads_enabled_categories(catalog, project, tmp_path):
    """默认补录 AI 消息，任务历史不占用名额且之后开启类别不会重新补录"""
    conversation = catalog.db.all("SELECT * FROM conversations")[0]
    job_id = uid()
    with catalog.db.transaction() as conn:
        conn.execute(
            "INSERT INTO messages VALUES (?,?,NULL,'user',?,?)",
            (uid(), conversation["id"], "合成历史消息", now()),
        )
        conn.execute(
            "INSERT INTO jobs(id,project_id,conversation_id,kind,status,request_json,"
            "created_at,request_key) VALUES (?,?,?,'chat','failed','{}',?,?)",
            (job_id, project["id"], conversation["id"], now(), uid()),
        )
    catalog.db.event(job_id, "error", {"text": "合成任务失败"})
    log = ActivityLog(tmp_path / "history.sqlite", max_records=1)
    log.import_history(catalog.db)
    assert log.page()["counts"] == {"ai": 1}
    assert log.page()["write_failures"] == 0
    save_capture_settings(log, ActivityCaptureSettings(categories=list(ACTIVITY_CATEGORIES)))
    restarted = ActivityLog(log.path, max_records=1)
    restarted.import_history(catalog.db)
    assert restarted.page()["counts"] == {"ai": 1}
    assert restarted.page()["cursor"] == 1
