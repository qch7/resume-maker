"""源码片段不拆分隐私占位符，按列续读保持完整及有界响应"""

import json
import threading

import pytest

from resume_maker.integrations.privacy import TOKEN, Redactor
from resume_maker.integrations.source_access import MAX_RESULT, SourceAccess
from resume_maker.sdk.model import ProviderError


def access_for(tmp_path, raw, *, redactor=None):
    """创建只含合成文本的单文件来源，换行按输入保留"""
    root = tmp_path / "source"
    root.mkdir()
    (root / "example.py").write_bytes(raw.encode("utf-8"))
    return SourceAccess(
        [{"id": "source-0", "path": str(root)}],
        tmp_path / "data",
        redactor or Redactor(["SensitiveName", "OtherPrivateName"]),
        threading.Event(),
    )


@pytest.mark.parametrize("prefix_length", [1980, 1990, 2000, 2001])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_read_pages_keep_whole_tokens_and_restore_without_gaps(tmp_path, prefix_length, newline):
    """分页命中左右边界或相邻占位符时，不重复、不丢失正文及换行位置"""
    prefix = "x; " * (prefix_length // 3) + " " * (prefix_length % 3)
    raw = prefix + "SensitiveNameOtherPrivateName" + " x;" * 1000 + newline + "last line"
    with access_for(tmp_path, raw) as access:
        args = {"source": "source-0", "path": "example.py"}
        restored, previous = {}, (1, 1)
        for _ in range(10):
            page = access.call("read_source", args)
            assert len(json.dumps(page, ensure_ascii=False)) <= MAX_RESULT
            for row in page["lines"]:
                restored.setdefault(row["line"], []).append(access.redactor.restore(row["text"]))
            if page["eof"]:
                break
            position = (page["next"]["start_line"], page["next"]["start_column"])
            assert position > previous
            previous = position
            args.update(page["next"])
        else:
            pytest.fail("占位符续页没有前进")
        assert ["".join(restored[line]) for line in sorted(restored)] == raw.split(newline)


def test_manual_column_inside_token_returns_whole_identity(tmp_path):
    """手工起点覆盖占位符首尾及内部，返回片段始终可以本机还原"""
    prefix = "x; " * 10
    with access_for(tmp_path, prefix + "SensitiveName tail") as access:
        safe = access.redactor.text(prefix + "SensitiveName tail")
        token = TOKEN.search(safe)
        for offset in range(token.start(), token.end() + 1):
            page = access.call(
                "read_source",
                {"source": "source-0", "path": "example.py", "start_column": offset + 1},
            )
            expected = "SensitiveName tail" if offset < token.end() else " tail"
            assert access.redactor.restore(page["lines"][0]["text"]) == expected
            assert page["eof"]


@pytest.mark.parametrize("side", ["left", "right"])
def test_search_snippet_boundaries_keep_tokens_and_columns(tmp_path, side):
    """搜索上下文边界落入占位符时同步修正列号，命中仍可还原"""
    raw = (
        "x; " * 10 + "SensitiveName" + "x; " * 36 + " xfind tail"
        if side == "left"
        else "find " + "x; " * 328 + " " + "SensitiveName tail"
    )
    with access_for(tmp_path, raw) as access:
        page = access.call("search_sources", {"query": "find"})
        assert page["complete"] and len(page["results"]) == 1
        row = page["results"][0]
        restored = access.redactor.restore(row["text"])
        assert "find" in restored
        if side == "left":
            assert row["column"] == 31
            assert restored.startswith("SensitiveName")
        else:
            assert row["column"] == 1 and len(row["text"]) == 990
            following = access.call(
                "read_source",
                {
                    "source": "source-0",
                    "path": "example.py",
                    "start_column": row["column"] + len(row["text"]),
                },
            )
            assert restored + access.redactor.restore(following["lines"][0]["text"]) == raw


@pytest.mark.parametrize("token_length", [2500, MAX_RESULT + 100])
@pytest.mark.parametrize("tool", ["read_source", "search_sources"])
def test_long_token_respects_hard_budget_without_empty_page_loop(tmp_path, token_length, tool):
    """超出软片段长度的完整占位符可读，超出响应预算则明确失败"""
    redactor = Redactor(["SensitiveName"])
    token = "[[RM_" + redactor.prefix + "_" + "1" * token_length + "]]"
    redactor.mapping["SensitiveName"] = token
    redactor.reverse[token] = "SensitiveName"
    redactor._token_length = len(token)
    with access_for(tmp_path, "SensitiveName tail", redactor=redactor) as access:
        args = (
            {"source": "source-0", "path": "example.py"}
            if tool == "read_source"
            else {"query": "SensitiveName"}
        )
        if token_length > MAX_RESULT:
            with pytest.raises(ProviderError, match="预算"):
                access.call(tool, args)
            assert not access.cursors
        else:
            page = access.call(tool, args)
            assert len(json.dumps(page, ensure_ascii=False)) <= MAX_RESULT
            rows = page["lines"] if tool == "read_source" else page["results"]
            assert TOKEN.fullmatch(rows[0]["text"])
            assert access.redactor.restore(rows[0]["text"]) == "SensitiveName"
            if tool == "read_source":
                assert page["next"]["start_column"] == len(token) + 1
                tail = access.call(tool, {**args, **page["next"]})
                assert tail["eof"] and tail["lines"][0]["text"] == " tail"


def test_malformed_token_restoration_remains_rejected():
    """分页修复不能放宽模型输出中损坏占位符的拒绝规则"""
    redactor = Redactor(["SensitiveName"])
    token = redactor.text("SensitiveName")
    with pytest.raises(ProviderError, match="损坏"):
        redactor.restore(token[:-2])


@pytest.mark.parametrize("tool", ["read_source", "search_sources"])
def test_whole_token_deferred_by_response_budget_resumes_once(tmp_path, tool):
    """本页剩余预算不足时保留整段，下页继续一次且不丢失已有结果"""
    redactor = Redactor(["SensitiveName"])
    token = "[[RM_" + redactor.prefix + "_" + "1" * 23000 + "]]"
    redactor.mapping["SensitiveName"] = token
    redactor.reverse[token] = "SensitiveName"
    redactor._token_length = len(token)
    first_line = "find " + "x; " * 330
    with access_for(tmp_path, first_line + "\nSensitiveName find", redactor=redactor) as access:
        args = (
            {"source": "source-0", "path": "example.py"}
            if tool == "read_source"
            else {"query": "find"}
        )
        restored = []
        for _ in range(4):
            page = access.call(tool, args)
            assert len(json.dumps(page, ensure_ascii=False)) <= MAX_RESULT
            rows = page["lines"] if tool == "read_source" else page["results"]
            assert rows
            restored.extend(redactor.restore(row["text"]) for row in rows)
            complete = page["eof"] if tool == "read_source" else page["complete"]
            if complete:
                break
            args.update(page["next"] if tool == "read_source" else {"cursor": page["next_cursor"]})
        else:
            pytest.fail("响应预算续页没有结束")
        assert restored[0] == first_line
        assert "".join(restored[1:]) == "SensitiveName find"
