"""源码全文件预处理的内存准入、缓存淘汰、取消边界"""

import threading

import pytest

from resume_maker.integrations import source_access
from resume_maker.integrations.privacy import Redactor
from resume_maker.integrations.source_access import SourceAccess
from resume_maker.sdk.model import ProviderError


def test_large_source_is_rejected_before_preparation_and_cache_is_bounded(tmp_path):
    """拒绝超出内存预算的全文，淘汰缓存后仍能重新读取全部授权文件"""
    root = tmp_path / "source"
    root.mkdir()
    for i in range(3):
        (root / f"small-{i}.py").write_text("x = 1\n" * 10)
    (root / "large.py").write_text("x = 1\n" * 100)
    with SourceAccess(
        [{"id": "source-0", "path": str(root)}],
        tmp_path / "data",
        Redactor([]),
        threading.Event(),
        max_file_bytes=100,
        max_cache_bytes=100,
    ) as access:
        with pytest.raises(ProviderError, match="预算"):
            access.call("read_source", {"source": "source-0", "path": "large.py", "line_count": 1})
        assert access.cache == {}
        for name in ["small-0.py", "small-1.py", "small-2.py", "small-0.py"]:
            assert access.call("read_source", {"source": "source-0", "path": name})["lines"]
            assert sum(row[2].stat().st_size for row in access.cache.values()) <= 100


def test_search_marks_large_file_unavailable_and_cursor_eviction_releases_iterator(
    tmp_path, monkeypatch
):
    """超限文件保留不可用标识，有限游标只回收旧查询且可重新开始"""
    root = tmp_path / "source"
    root.mkdir()
    (root / "large.py").write_text("x = 1\n" * 100)
    closed = []
    monkeypatch.setattr(source_access, "MAX_SOURCE_CURSORS", 2)
    with SourceAccess(
        [{"id": "source-0", "path": str(root)}],
        tmp_path / "data",
        Redactor([]),
        threading.Event(),
        max_file_bytes=100,
    ) as access:
        result = access.call("search_sources", {"query": "x"})
        assert result["complete"] and "预算" in result["results"][0]["unavailable"]

        def entries(source, pattern):
            """提供足够长的扫描以留下待继续游标"""
            try:
                for _ in range(1001):
                    yield None
            finally:
                closed.append(pattern)

        monkeypatch.setattr(access, "entries", entries)
        cursors = [
            access.call("list_source_files", {"glob": str(i)})["next_cursor"] for i in range(3)
        ]
        assert len(access.cursors) == 2 and closed == ["0"]
        with pytest.raises(ValueError, match="游标"):
            access.call("list_source_files", {"glob": "0", "cursor": cursors[0]})
        assert access.call("list_source_files", {"glob": "0"})["next_cursor"]
    assert len(closed) == 4


def test_response_budget_serializes_each_row_without_repeating_prefix(tmp_path, monkeypatch):
    """读取、列表只编码单条记录计算预算，避免对已有结果反复序列化"""
    root = tmp_path / "source"
    root.mkdir()
    (root / "many.py").write_text("ordinary\n" * 250, encoding="utf-8")
    with SourceAccess(
        [{"id": "source-0", "path": str(root)}], tmp_path / "data", Redactor(), threading.Event()
    ) as access:
        access.prepared("source-0", "many.py")
        original, visits = source_access.json.dumps, []

        def counted(value, **kwargs):
            """编码器应只见到空响应外壳或单条记录"""
            if isinstance(value, list):
                assert not value
            if isinstance(value, dict):
                assert not value.get("lines")
                visits.append(value)
            return original(value, **kwargs)

        monkeypatch.setattr(source_access.json, "dumps", counted)
        result = access.call(
            "read_source", {"source": "source-0", "path": "many.py", "line_count": 200}
        )
        assert len(result["lines"]) == 200 and result["next"]["start_line"] == 201
        assert len(visits) <= 202
        visits.clear()

        def listing(*_):
            """生成短条目，确保达到条数边界而非字数边界"""
            yield from ({"source": "source-0", "path": f"part-{i}.py"} for i in range(110))

        monkeypatch.setattr(access, "listing", listing)
        result = access.call("list_source_files", {})
        assert len(result["results"]) == 100 and len(visits) == 100
