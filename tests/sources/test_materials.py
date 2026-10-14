"""材料服务的长行分段、完整 JSON 响应"""

import json

import pytest

from resume_maker.integrations.providers import material_server
from resume_maker.integrations.providers.material_server import MaterialSearch, call, dispatch


def test_material_long_line_can_be_read_completely_and_searched(tmp_path):
    """长行分段可完整重组且搜索片段包含实际命中，响应始终为有界 JSON"""
    original = '\\"\t' * 9000 + "FUNCTION_AT_END"
    (tmp_path / "source-0001.txt").write_text(original + "\nlast line", encoding="utf-8")
    column, pieces = 1, []
    for _ in range(100):
        raw = call(
            tmp_path,
            "read_material",
            {"file": "source-0001.txt", "start_line": 1, "start_column": column, "line_count": 1},
        )
        assert len(raw) <= 24000
        rows = json.loads(raw)
        assert len(rows) == 1 and rows[0]["line"] == 1
        pieces.append(rows[0]["text"])
        if "next_column" not in rows[0]:
            break
        assert rows[0]["next_column"] > column
        column = rows[0]["next_column"]
    else:
        pytest.fail("长行读取未完成")
    assert "".join(pieces) == original
    matches = json.loads(call(tmp_path, "search_materials", {"query": "FUNCTION_AT_END"}))[
        "results"
    ]
    assert matches[0]["line"] == 1 and "FUNCTION_AT_END" in matches[0]["text"]


def test_material_many_matches_do_not_truncate_json(tmp_path):
    """多个长匹配行触及输出上限时只返回完整记录，可按行号继续读取"""
    (tmp_path / "source-0001.txt").write_text(
        "\n".join("needle" + "x" * 900 for _ in range(100)), encoding="utf-8"
    )
    for tool, arguments in (
        ("search_materials", {"query": "needle"}),
        ("read_material", {"file": "source-0001.txt", "line_count": 100}),
    ):
        raw = call(tmp_path, tool, arguments)
        assert len(raw) <= 24000
        rows = json.loads(raw)
        if tool == "search_materials":
            rows = rows["results"]
        assert rows and all(row["text"].startswith("needle") for row in rows)


def test_search_continues_after_dense_file_and_response_limit(tmp_path, monkeypatch):
    """字数、条数边界后的命中及后续材料都能完整取回"""
    (tmp_path / "source-0001.txt").write_text(
        "\n".join("needle " + '\\"\t' * 300 for _ in range(230)), encoding="utf-8"
    )
    (tmp_path / "source-0002.txt").write_text("needle final implementation", encoding="utf-8")
    loaded, original = [], material_server.contents

    def counted(root, name):
        """连续分页复用已核验材料，避免反复读取同一个完整文件"""
        loaded.append(name)
        return original(root, name)

    monkeypatch.setattr(material_server, "contents", counted)
    searches, args, rows = MaterialSearch(tmp_path), {"query": "needle"}, []
    for _ in range(100):
        raw = call(tmp_path, "search_materials", args, searches=searches)
        assert len(raw) <= 24000
        result = json.loads(raw)
        rows.extend(result["results"])
        if result["complete"]:
            assert result["next_cursor"] is None
            break
        args["cursor"] = result["next_cursor"]
    else:
        pytest.fail("静态材料搜索未完成")
    assert [(row["file"], row["line"]) for row in rows] == [
        *[("source-0001.txt", index) for index in range(1, 231)],
        ("source-0002.txt", 1),
    ]
    assert searches.cursors == {}
    assert loaded == ["source-0001.txt", "source-0002.txt"]


def test_empty_search_page_continues_and_mcp_preserves_cursor(tmp_path):
    """没有命中的千行页仍能通过材料进程的相同状态继续搜索"""
    (tmp_path / "context.txt").write_text("ordinary\n" * 1200 + "needle\n", encoding="utf-8")
    searches = MaterialSearch(tmp_path)
    request = {
        "method": "tools/call",
        "params": {"name": "search_materials", "arguments": {"query": "needle"}},
    }
    first = json.loads(dispatch(tmp_path, request, searches=searches)["content"][0]["text"])
    assert first["results"] == [] and not first["complete"]
    request["params"]["arguments"]["cursor"] = first["next_cursor"]
    last = json.loads(dispatch(tmp_path, request, searches=searches)["content"][0]["text"])
    assert last["results"][0]["line"] == 1201 and last["complete"]


def test_material_cursors_reject_scope_changes_and_eviction(tmp_path, monkeypatch):
    """游标绑定实例、查询，过期及任务关闭后拒绝重用"""
    (tmp_path / "context.txt").write_text("needle\n" * 101, encoding="utf-8")
    monkeypatch.setattr(material_server, "MAX_CURSORS", 2)
    searches = MaterialSearch(tmp_path)
    first = json.loads(searches.search({"query": "needle"}))["next_cursor"]
    with pytest.raises(ValueError, match="查询条件"):
        searches.search({"query": "other", "cursor": first})
    with pytest.raises(ValueError, match="不属于"):
        MaterialSearch(tmp_path).search({"query": "needle", "cursor": first})
    for _ in range(2):
        searches.search({"query": "needle"})
    with pytest.raises(ValueError, match="不属于"):
        searches.search({"query": "needle", "cursor": first})
    last = next(iter(searches.cursors))
    searches.close()
    with pytest.raises(ValueError, match="不属于"):
        searches.search({"query": "needle", "cursor": last})


def test_material_change_invalidates_search_continuation(tmp_path):
    """续页复核文件状态，材料替换后不能套用旧行位置"""
    file = tmp_path / "context.txt"
    file.write_text("needle\n" * 101, encoding="utf-8")
    searches = MaterialSearch(tmp_path)
    first = json.loads(searches.search({"query": "needle"}))
    file.write_text("different material", encoding="utf-8")
    with pytest.raises(ValueError, match="已变化"):
        searches.search({"query": "needle", "cursor": first["next_cursor"]})
