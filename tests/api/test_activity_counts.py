"""实时计数复用基线并处理晚到隐藏、跨实例删除及并发旧快照"""

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from resume_maker.infrastructure.activity import MAX_COUNTS_DELTA, ActivityLog
from resume_maker.infrastructure.database import now


@pytest.fixture
def log(tmp_path):
    """完整采集的独立日志只使用合成记录，批量基准保留足够容量"""
    result = ActivityLog(tmp_path / "activity.sqlite", max_records=100000)
    result.capture_categories = frozenset({"api", "ai", "service", "tool"})
    result.capture_starts = True
    return result


def insert_rows(log, rows):
    """一次事务写入合成历史，避免大量独立连接掩盖查询工作量"""
    stamp = now()
    with closing(log.connect()) as conn, conn:
        conn.executemany(
            "INSERT INTO activity(created_at,category,level,source,event,title,trace_id,"
            "payload_json) VALUES (? ,?,'info','synthetic',?,?,?,'{}')",
            ((stamp, *row) for row in rows),
        )
        log._remember_cursor(conn, log._cursor(conn))


def test_idle_poll_reuses_counts_and_delete_invalidates(tmp_path, monkeypatch):
    """空增量复用计数，删除及新记录仍立即改变总数"""
    log = ActivityLog(tmp_path / "activity.db")
    for i in range(20):
        log.write("ai", "message", str(i))
    queries = []
    original = log.connect

    def connect(**kwargs):
        """只计数真正执行的全历史统计 SQL"""
        conn = original(**kwargs)
        conn.set_trace_callback(queries.append)
        return conn

    monkeypatch.setattr(log, "connect", connect)
    page = log.page()
    for _ in range(10):
        assert log.page(after=page["cursor"])["events"] == []
    assert sum("SELECT category,COUNT(*)" in query for query in queries) == 1
    page = log.page(hide_polling=True, hidden_rules="/api/state")
    queries.clear()
    for _ in range(10):
        assert (
            log.page(after=page["cursor"], hide_polling=True, hidden_rules="/api/state")["events"]
            == []
        )
    assert not any("hidden_polling" in query or "COUNT(*)" in query for query in queries)
    log.delete(before=None)
    assert log.page(after=page["cursor"])["total"] == 0
    log.write("ai", "message", "new")
    assert log.page(after=page["cursor"])["total"] == 1


def test_another_log_instance_invalidates_deletion_and_filter_caches(tmp_path):
    """同库另一个实例的删除立即失效，筛选结果、不同目录仍独立"""
    left = ActivityLog(tmp_path / "shared.db")
    left.write("ai", "message", "one")
    peer = ActivityLog(tmp_path / "shared.db")
    other = ActivityLog(tmp_path / "other.db")
    assert left.page(category="ai")["total"] == 1
    assert left.page(category="tool")["total"] == 0
    peer.delete(before=None)
    assert left.page(category="ai")["total"] == 0
    other.write("ai", "message", "isolated")
    assert other.page()["total"] == 1 and left.page()["total"] == 0


def test_noop_pruning_keeps_delta_baseline(log, monkeypatch):
    """例行修剪没有删除时仍可增量计数，不因游标跨整百重扫历史"""
    insert_rows(log, [("ai", "message", "history", "")] * 99)
    page = log.page()
    queries = []
    original = log.connect

    def connect(**kwargs):
        """观察跨越修剪点后的统计范围"""
        conn = original(**kwargs)
        conn.set_trace_callback(queries.append)
        return conn

    monkeypatch.setattr(log, "connect", connect)
    log.write("ai", "message", "new")
    assert log.page(after=page["cursor"])["counts"] == {"ai": 100}
    assert len(log.counts_cache) == 1
    counts = [query for query in queries if "SELECT category,COUNT(*)" in query]
    assert len(counts) == 1 and "id>99" in counts[0]
    assert not any(
        "INSERT INTO metadata(key,value) VALUES ('counts_revision'" in query for query in queries
    )


@pytest.mark.parametrize(
    "filters",
    [
        {},
        {"category": "service"},
        {"level": "info"},
        {"q": "read"},
        {"show_starts": False},
        {"trace_id": "pending"},
        {"since": "2000-01-01", "until": "9999-01-01"},
    ],
)
def test_late_success_delta_matches_full_filtered_counts(log, filters):
    """成功响应撤回旧读取，重复响应不重复扣减，筛选和原始链路继续一致"""
    query = {"hide_polling": True, "hidden_rules": "/api/state", **filters}
    log.write("api", "request", "GET /api/state", trace_id="pending")
    log.write("service", "started", "read started", trace_id="pending")
    log.write("service", "completed", "read slow", trace_id="pending", duration_ms=1200)
    log.write("service", "completed", "read warning", trace_id="pending", level="warning")
    log.write("ai", "message", "read ai", trace_id="pending")
    page = log.page(**query)
    for title in ("GET /api/state · 200", "GET /api/state · 304"):
        log.write("api", "response", title, trace_id="pending")
        log.write("tool", "completed", "read tool", trace_id="pending")
        incremental = log.page(after=page["cursor"], **query)
        log.counts_cache.clear()
        complete = log.page(**query)
        assert incremental["counts"] == complete["counts"]
        assert incremental["total"] == complete["total"]
        page = incremental


def test_new_maintenance_parent_rechecks_old_child_visibility(log, monkeypatch):
    """父维护跨度晚到时回退全算，不能把已显示的内部读取永久计入总数"""
    query = {"hide_polling": True, "hidden_rules": "template_library.purge_expired"}
    log.write(
        "service", "completed", "child", source="template_library.state", parent_span_id="purge"
    )
    page = log.page(**query)
    assert page["total"] == 1
    log.write(
        "service", "started", "parent", source="template_library.purge_expired", span_id="purge"
    )
    assert log.page(after=page["cursor"], **query)["total"] == 0


def test_peer_pruning_invalidates_counts_without_reusing_old_snapshot(log):
    """另一实例的真实容量修剪推进代次，原实例立即返回剩余数量"""
    insert_rows(log, [("ai", "message", "history", "")] * 12)
    page = log.page()
    peer = ActivityLog(log.path, max_records=3)
    assert peer.page()["total"] == 3
    assert log.page(after=page["cursor"])["counts"] == {"ai": 3}


def test_older_read_cannot_replace_newer_baseline(log, monkeypatch):
    """先开始的读取最后完成时，返回自身快照但保留缓存中的较新计数"""
    log.write("ai", "message", "first")
    log.page()
    log.write("ai", "message", "second")
    ready, release = threading.Event(), threading.Event()
    original = log._counts

    def delayed(conn, snapshot, *args):
        """在旧事务建立快照后等待另一读取更新基线"""
        if snapshot == 2:
            ready.set()
            assert release.wait(5)
        return original(conn, snapshot, *args)

    monkeypatch.setattr(log, "_counts", delayed)
    with ThreadPoolExecutor(max_workers=1) as executor:
        old = executor.submit(log.page)
        assert ready.wait(5)
        try:
            log.write("ai", "message", "third")
            assert log.page()["total"] == 3
        finally:
            release.set()
        assert old.result()["total"] == 2
    assert [baseline[0] for baseline in log.counts_cache.values()] == [3]
    assert log.page()["total"] == 3


def test_many_retracted_traces_and_large_gap_fallback(log, monkeypatch):
    """支持完整增量上限的多链路差额，超过范围后使用当前全量快照"""
    query = {"hide_polling": True, "hidden_rules": "/api/state"}
    insert_rows(
        log, [("service", "completed", "read", f"trace-{i}") for i in range(MAX_COUNTS_DELTA)]
    )
    page = log.page(**query)
    assert page["total"] == MAX_COUNTS_DELTA
    insert_rows(
        log,
        [
            ("api", "response", "GET /api/state · 200", f"trace-{i}")
            for i in range(MAX_COUNTS_DELTA)
        ],
    )
    page = log.page(after=page["cursor"], **query)
    assert page["counts"] == {}
    assert len(page["hidden_trace_ids"]) == MAX_COUNTS_DELTA
    insert_rows(log, [("ai", "message", "new", "")] * (MAX_COUNTS_DELTA + 1))

    def unexpected_delta(*args):
        """大跨度必须走完整快照，不能构造无界链路差额"""
        pytest.fail("超过增量上限仍进入差额计算")

    monkeypatch.setattr(log, "_delta_counts", unexpected_delta)
    assert log.page(after=page["cursor"], **query)["counts"] == {"ai": MAX_COUNTS_DELTA + 1}


def test_counts_cache_is_bounded_per_filter(log):
    """任意搜索条件只能占用固定数量基线，不能随轮询游标增长"""
    log.write("ai", "message", "sample")
    for index in range(40):
        log.page(q=str(index))
    assert len(log.counts_cache) == 32


def test_mixed_large_history_delta_avoids_full_sql_work(log, monkeypatch):
    """五万条混合历史中新增少量事件只做区间统计，空链路不会触发全历史索引扫描"""
    rows = []
    for index in range(12500):
        rows.extend(
            [
                ("api", "request", "GET /api/state", f"poll-{index}"),
                ("api", "response", "GET /api/state · 200", f"poll-{index}"),
                ("ai", "message", "first", ""),
                ("ai", "message", "second", ""),
            ]
        )
    insert_rows(log, rows)
    query = {"hide_polling": True}
    page = log.page(**query)
    log.write("api", "response", "GET /api/state · 200", trace_id="new")
    log.write("ai", "message", "new ai")
    steps = []
    original = log.connect

    def connect(**kwargs):
        """用虚拟机指令数衡量数据库扫描工作，避免机器耗时波动"""
        conn = original(**kwargs)
        conn.set_progress_handler(lambda: steps.append(100), 100)
        return conn

    monkeypatch.setattr(log, "connect", connect)
    incremental = log.page(after=page["cursor"], **query)
    incremental_steps = sum(steps)
    log.counts_cache.clear()
    steps.clear()
    complete = log.page(after=page["cursor"], **query)
    assert incremental["counts"] == complete["counts"] == {"ai": 25001}
    assert incremental_steps * 20 < sum(steps)
