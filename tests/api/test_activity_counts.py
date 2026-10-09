"""实时日志计数在没有变化时不重复扫描历史"""

from resume_maker.infrastructure.activity import ActivityLog


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
    """同库另一个实例的删除立即失效，筛选结果和不同目录仍独立"""
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
