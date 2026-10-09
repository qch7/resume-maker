"""源码全文件预处理的内存准入、缓存淘汰和取消边界"""

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
