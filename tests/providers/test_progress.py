"""源码进度仅统计受信任通道真正完成的读取，不公开路径或参数"""

import json
import threading
from types import SimpleNamespace

import pytest

from resume_maker.integrations.providers.material_server import source_call
from resume_maker.integrations.providers.source_broker import source_broker
from resume_maker.plugin_packages.ext_provider_codex.integrations.providers.progress import (
    SourceProgress,
)


def test_source_progress_counts_successful_reads_without_private_details():
    """重复分段只计一个文件，列表搜索计工具次数，拒绝的读取不推进计数"""
    events = []
    progress = SourceProgress(lambda kind, data: events.append((kind, data)))

    def call(name, arguments):
        """模拟实际授权通道的成功、拒绝结果"""
        if arguments.get("path") == "../private":
            raise ValueError("拒绝访问私密目录")
        return {"text": "private-result"}

    access = SimpleNamespace(call=call, stopped=threading.Event())
    with source_broker(access, on_read=progress.read) as endpoint:
        source_call(endpoint, "list_source_files", {})
        for line in [1, 10]:
            source_call(
                endpoint,
                "read_source",
                {
                    "source": "source-0",
                    "path": "private-name.py",
                    "start_line": line,
                },
            )
        source_call(endpoint, "search_sources", {"query": "private-query"})
        with pytest.raises(ValueError):
            source_call(endpoint, "read_source", {"source": "source-0", "path": "../private"})
    assert len(events) == 4
    assert events[-1][1]["files_read"] == 1
    assert events[-1][1]["tool_calls"] == 4
    assert all(
        value not in json.dumps(events)
        for value in [
            "private-name",
            "private-result",
            "private-query",
            "../private",
            endpoint["token"],
        ]
    )
