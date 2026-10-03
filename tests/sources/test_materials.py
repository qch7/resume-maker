"""材料服务的长行分段和完整 JSON 响应"""

import json

import pytest

from resume_maker.integrations.providers.material_server import call


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
    matches = json.loads(call(tmp_path, "search_materials", {"query": "FUNCTION_AT_END"}))
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
        assert rows and all(row["text"].startswith("needle") for row in rows)
