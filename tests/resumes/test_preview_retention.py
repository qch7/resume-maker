"""预览预算、使用顺序、下载租约和失败产物回收"""

import asyncio

import pytest

from resume_maker.api.resources import LeasedFileResponse
from resume_maker.core.errors import Problem
from resume_maker.sdk.previews import PreviewCache


def publish(cache, content=b"preview", owner="test"):
    """在实例专有目录创建一个可下载的合成预览"""
    with cache.allocate() as (identifier, path):
        (path / "resume.docx").write_bytes(content)
        cache.publish(identifier, path, {"resume.docx"}, owner=owner)
    return identifier


def test_preview_lru_and_bytes_preserve_active_downloads(tmp_path):
    """条目和字节限制同时生效，传输中的旧页保持可读且不阻塞发布"""
    cache = PreviewCache(tmp_path, prefix="test-", max_entries=2, max_bytes=14)
    try:
        first, second = publish(cache), publish(cache)
        with cache.lease(first, "resume.docx", owner="test") as path:
            third = publish(cache)
            assert path.read_bytes() == b"preview"
            assert not cache.touch(second)
            with pytest.raises(Problem, match="正在下载"):
                cache.artifacts("test")
            with cache.lease(third, "resume.docx"):
                with pytest.raises(Problem, match="容量已满"):
                    publish(cache)
        assert len(list(cache.workspace.glob("test-*/*"))) == 2
        cache.touch(first)
        publish(cache, b"larger preview")
        assert not cache.touch(first) and not cache.touch(third)
        assert len(cache.entries) == 1
    finally:
        cache.stop()
    assert list(tmp_path.iterdir()) == []


def test_failed_and_oversized_previews_are_removed(tmp_path):
    """渲染异常或超预算的部分产物不留下永久目录"""
    cache = PreviewCache(tmp_path, prefix="test-", max_bytes=10)
    try:
        with pytest.raises(RuntimeError):
            with cache.allocate() as (_, path):
                (path / "partial.docx").write_bytes(b"partial")
                raise RuntimeError("模拟渲染异常")
        with pytest.raises(Problem, match="容量上限"):
            publish(cache, b"too large to retain")
        assert not cache.entries
        assert list(cache.workspace.glob("test-*/*")) == []
    finally:
        cache.stop()


@pytest.mark.parametrize("disconnect", [False, True])
def test_file_response_holds_lease_until_complete_or_disconnected(tmp_path, disconnect):
    """响应真正发送期间不能回收文件，客户端断开也归还租约"""
    cache = PreviewCache(tmp_path, prefix="response-", max_entries=1)
    identifier = publish(cache)

    async def receive():
        """提供不含断开事件的合成 ASGI 接收端"""
        return {"type": "http.request"}

    async def send(message):
        """传输中尝试发布新预览，旧页必须保持完整可读"""
        assert cache.entries[identifier]["leases"] == 1
        with pytest.raises(Problem, match="容量已满"):
            publish(cache)
        assert cache.file(identifier, "resume.docx").read_bytes() == b"preview"
        if disconnect:
            raise RuntimeError("模拟客户端断开")

    response = LeasedFileResponse(lambda: cache.lease(identifier, "resume.docx"), "resume.docx")
    try:
        if disconnect:
            with pytest.raises(RuntimeError, match="断开"):
                asyncio.run(
                    response({"type": "http", "method": "GET", "headers": []}, receive, send)
                )
        else:
            asyncio.run(response({"type": "http", "method": "GET", "headers": []}, receive, send))
        assert cache.entries[identifier]["leases"] == 0
        publish(cache)
        assert not cache.touch(identifier)
    finally:
        cache.stop()
