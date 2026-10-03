"""验证源码按需访问恢复大项目能力，同时保持原件和身份隔离"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from resume_maker.core import config
from resume_maker.integrations.privacy import Redactor
from resume_maker.integrations.providers import material_server
from resume_maker.integrations.providers.base import Cancelled
from resume_maker.integrations.providers.material_server import dispatch, source_call
from resume_maker.integrations.providers.source_broker import source_broker
from resume_maker.integrations.source_access import SourceAccess
from resume_maker.integrations.source_context import source_context
from resume_maker.integrations.sources import evidence_file


def access_at(tmp_path, values=()):
    """为两个独立合成目录创建本轮网关"""
    roots = [tmp_path / "first", tmp_path / "second"]
    for root in roots:
        root.mkdir(exist_ok=True)
    sources = [{"id": f"source-{i}", "path": str(root)} for i, root in enumerate(roots)]
    return SourceAccess(sources, tmp_path / "data", Redactor(values), threading.Event())


def pages(access, name, args):
    """跟随服务返回的游标，确认空页也不会被误认为搜索结束"""
    result = []
    for _ in range(1000):
        page = access.call(name, args)
        assert len(json.dumps(page, ensure_ascii=False)) <= 24000
        result.extend(page["results"])
        if page["complete"]:
            assert page["next_cursor"] is None
            return result
        assert page["next_cursor"]
        args = {**args, "cursor": page["next_cursor"]}
    pytest.fail("分页没有结束")


def test_model_start_does_not_collect_source(tmp_path, monkeypatch):
    """建立模型上下文不扫描整库，大目录不影响启动"""
    with access_at(tmp_path) as access:

        def forbidden(*_args, **_kwargs):
            """提前遍历或读取源码意味着旧的预采集重新出现"""
            pytest.fail("不得预采集")

        with monkeypatch.context() as patch:
            patch.setattr(os, "walk", forbidden)
            patch.setattr(Path, "read_bytes", forbidden)
            value = source_context(access.sources, access.data_dir, access.cancelled)
            assert value["mode"] == "on-demand" and value["sources"] == ["source-0", "source-1"]
            assert "files" not in value


def test_more_than_200_files_and_350000_characters_remain_accessible(tmp_path):
    """后续来源和文件超过旧总量限制后仍能列出、搜索和读取"""
    with access_at(tmp_path) as access:
        for number in range(230):
            (tmp_path / "first" / f"part-{number:04}.py").write_text(
                "# ordinary source line\n" * 80, encoding="utf-8"
            )
        target = tmp_path / "second" / "last.py"
        target.write_text("def final_capability():\n    return 42\n", encoding="utf-8")
        rows = pages(access, "list_source_files", {})
        assert len(rows) == 231 and rows[-1]["source"] == "source-0"
        matches = pages(access, "search_sources", {"query": "final_capability"})
        assert [(row["source"], row["path"], row["line"]) for row in matches] == [
            ("source-1", "last.py", 1)
        ]
        value = access.call(
            "read_source", {"source": "source-1", "path": "last.py", "start_line": 2}
        )
        assert value["lines"] == [{"line": 2, "text": "    return 42"}]


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_large_file_tail_and_private_citations(tmp_path, encoding, newline):
    """大于旧单文件限制的末尾实现可读且身份证明在本机准确还原"""
    with access_at(tmp_path, ["合成私密姓名"]) as access:
        raw = newline.join(["# ordinary source content"] * 12000 + ["print('合成私密姓名')"])
        path = tmp_path / "first" / "合成私密姓名.py"
        path.write_bytes(raw.encode(encoding))
        rows = pages(access, "list_source_files", {"source": "source-0"})
        assert len(rows) == 1 and "合成私密姓名" not in rows[0]["path"]
        value = access.call("read_source", {**rows[0], "start_line": 12001})
        assert "合成私密姓名" not in json.dumps(value, ensure_ascii=False)
        restored = access.redactor.restore(value)
        assert restored["path"] == path.name
        assert restored["lines"] == [{"line": 12001, "text": "print('合成私密姓名')"}]
        assert path.read_bytes() == raw.encode(encoding)


def test_long_line_can_be_read_without_a_file_size_cutoff(tmp_path):
    """超过 128 KB 的单行可按列完整读取，不跳过行尾实现"""
    with access_at(tmp_path) as access:
        raw = "x = 1; " * 20000 + "TAIL_FEATURE"
        (tmp_path / "first" / "long.py").write_text(raw, encoding="utf-8")
        args = {"source": "source-0", "path": "long.py"}
        chunks = []
        for _ in range(200):
            value = access.call("read_source", args)
            chunks.extend(row["text"] for row in value["lines"])
            if value["eof"]:
                break
            args.update(value["next"])
        assert "".join(chunks) == raw
        matches = pages(access, "search_sources", {"query": "TAIL_FEATURE"})
        assert "TAIL_FEATURE" in matches[0]["text"]


def test_more_than_10000_entries_are_not_permanently_omitted(tmp_path, monkeypatch):
    """遍历跨过旧的一万项边界后仍能通过下一页到达目标文件"""
    from resume_maker.integrations import source_access

    with access_at(tmp_path) as access:
        path = tmp_path / "first" / "last.py"
        path.write_text("late implementation", encoding="utf-8")

        def many_entries(*_):
            """用目录进度标记模拟超大树，不生成一万个磁盘目录"""
            yield from [None] * 10005
            yield path

        monkeypatch.setattr(source_access, "source_paths", many_entries)
        rows = pages(access, "list_source_files", {"source": "source-0"})
        assert rows == [{"source": "source-0", "path": "last.py"}]


def test_source_access_rejects_unlinked_private_paths_and_hardlinks(tmp_path):
    """按需工具不能越界、读凭据、应用数据库或硬链接，同时保留普通源码目录"""
    with access_at(tmp_path) as access:
        root = tmp_path / "first"
        (root / "data").mkdir()
        (root / "data" / "model.py").write_text("ordinary model code")
        (root / "uv.lock").write_text("version = 1")
        for name in (".env", "private.pem"):
            (root / name).write_text("PRIVATE-CANARY")
        outside = tmp_path / "outside.txt"
        outside.write_text("PRIVATE-CANARY")
        os.link(outside, root / "hard.py")
        data = root / "app-private"
        data.mkdir()
        (data / "resume.txt").write_text("PRIVATE-CANARY")
        access.data_dir = data
        rows = pages(access, "list_source_files", {})
        assert {row["path"] for row in rows} == {"data/model.py", "uv.lock"}
        for path in (
            "../outside.txt",
            str(outside),
            ".env",
            "private.pem",
            "hard.py",
            "app-private/resume.txt",
            "uv.lock:secret",
        ):
            with pytest.raises((ValueError, OSError)):
                access.call("read_source", {"source": "source-0", "path": path})
        with pytest.raises(ValueError):
            access.call("read_source", {"source": "source-9", "path": "uv.lock"})


@pytest.mark.parametrize("selection", ["project", "sandbox", "task", "control"])
def test_project_sandbox_never_becomes_source_material(tmp_path, monkeypatch, selection):
    """项目沙箱及其子目录即使被直接选为来源，也不能列出、搜索、读取或留存证据"""
    project = tmp_path / "project"
    control = project / "ResumeMakerSandbox/task-synthetic/control"
    control.mkdir(parents=True)
    (project / "pyproject.toml").write_text('[project]\nname="resume-maker"\n')
    private = control / "session.txt"
    private.write_text("PRIVATE-CANARY", encoding="utf-8")
    monkeypatch.setattr(config, "__file__", str(project / "src/resume_maker/core/config.py"))
    selected = {
        "project": project,
        "sandbox": control.parent.parent,
        "task": control.parent,
        "control": control,
    }[selection]
    ordinary = tmp_path / "ordinary/ResumeMakerSandbox"
    ordinary.mkdir(parents=True)
    (ordinary / "main.py").write_text("ORDINARY-CANARY", encoding="utf-8")
    sources = [
        {"id": "source-0", "path": str(selected)},
        {"id": "source-1", "path": str(ordinary)},
    ]
    data_dir = tmp_path / "data"
    with SourceAccess(sources, data_dir, Redactor(), threading.Event()) as access:
        rows = pages(access, "list_source_files", {})
        assert {row["path"] for row in rows if row["source"] == "source-0"} == (
            {"pyproject.toml"} if selection == "project" else set()
        )
        assert {row["path"] for row in rows if row["source"] == "source-1"} == {"main.py"}
        assert pages(access, "search_sources", {"query": "PRIVATE-CANARY"}) == []
        path = private.relative_to(selected).as_posix()
        with pytest.raises(ValueError):
            access.call("read_source", {"source": "source-0", "path": path})
        with pytest.raises(ValueError):
            evidence_file(sources, "source-0", path, data_dir)


def test_cursor_scope_changes_and_cancellation(tmp_path):
    """游标绑定请求和查询条件，取消后不得继续返回材料"""
    with access_at(tmp_path) as access, access_at(tmp_path) as other:
        for i in range(110):
            (tmp_path / "first" / f"part-{i}.py").write_text("pass")
        first = access.call("list_source_files", {"source": "source-0"})
        cursor = first["next_cursor"]
        with pytest.raises(ValueError):
            other.call("list_source_files", {"source": "source-0", "cursor": cursor})
        with pytest.raises(ValueError):
            access.call("list_source_files", {"source": "source-1", "cursor": cursor})
        access.cancelled.set()
        with pytest.raises(Cancelled):
            access.call("list_source_files", {"source": "source-0", "cursor": cursor})


def test_broker_and_mcp_only_return_redacted_source(tmp_path):
    """真实本机通道只能返回脱敏结果，拒绝未知凭据及外部文件请求"""
    with access_at(tmp_path, ["合成私密姓名"]) as access:
        (tmp_path / "first" / "main.py").write_text("print('合成私密姓名')", encoding="utf-8")
        with source_broker(access) as endpoint:
            reply = source_call(endpoint, "read_source", {"source": "source-0", "path": "main.py"})
            assert "合成私密姓名" not in reply and "[[RM_" in reply
            assert "token" not in reply and str(tmp_path) not in reply
            with pytest.raises(ValueError):
                source_call({**endpoint, "token": "wrong"}, "list_source_files", {})
            denied = dispatch(
                tmp_path,
                {
                    "method": "tools/call",
                    "params": {
                        "name": "read_source",
                        "arguments": {"source": "source-0", "path": "../outside"},
                    },
                },
                endpoint,
            )
            assert denied["isError"]
        with pytest.raises(Cancelled):
            access.call("list_source_files", {})


def test_search_pages_survive_later_redaction_and_cache_refresh(tmp_path):
    """暂停搜索后读取新身份字段，后续命中仍完整且不泄露新发现的值"""
    with access_at(tmp_path) as access:
        (tmp_path / "first" / "many.py").write_text(
            "find SynthPrivate " + "q = 0; " * 200 + "\n" + ("find SynthPrivate\n" * 239),
            encoding="utf-8",
        )
        (tmp_path / "first" / "identity.txt").write_text("姓名：SynthPrivate", encoding="utf-8")
        args = {"query": "find", "glob": "many.py"}
        first = access.call("search_sources", args)
        assert not first["complete"]
        access.call("read_source", {"source": "source-0", "path": "identity.txt"})
        access.call("read_source", {"source": "source-0", "path": "many.py"})
        rest = pages(access, "search_sources", {**args, "cursor": first["next_cursor"]})
        assert [row["line"] for row in first["results"] + rest] == list(range(1, 241))
        assert "SynthPrivate" not in json.dumps(rest)
        assert "SynthPrivate" in access.redactor.restore(rest)[0]["text"]


def test_search_size_limit_resumes_inside_a_hundred_line_batch(tmp_path):
    """长命中在百行批次中间触发响应上限，续页仍逐行完整返回且不重复"""
    with access_at(tmp_path) as access:
        (tmp_path / "first" / "many.py").write_text(
            ("find " + "q = 0; " * 200 + "\n") * 245, encoding="utf-8"
        )
        args = {"query": "find", "glob": "many.py"}
        first = access.call("search_sources", args)
        assert 0 < len(first["results"]) < 100
        assert len(json.dumps(first, ensure_ascii=False)) <= 24000
        assert not first["complete"]
        rest = pages(access, "search_sources", {**args, "cursor": first["next_cursor"]})
        assert [row["line"] for row in first["results"] + rest] == list(range(1, 246))


def test_mcp_subprocess_remains_available_after_500_requests(tmp_path):
    """独立材料进程跨过旧生命周期上限后仍可通过本轮网关读取源码"""
    with access_at(tmp_path, ["合成私密姓名"]) as access:
        (tmp_path / "first" / "main.py").write_text("print('合成私密姓名')", encoding="utf-8")
        materials, control = tmp_path / "materials", tmp_path / "control"
        materials.mkdir()
        control.mkdir()
        with source_broker(access) as endpoint:
            config = control / "source-access.json"
            config.write_text(json.dumps(endpoint), encoding="utf-8")
            requests = [{"id": i, "method": "ping"} for i in range(501)]
            requests.append(
                {
                    "id": 501,
                    "method": "tools/call",
                    "params": {
                        "name": "read_source",
                        "arguments": {"source": "source-0", "path": "main.py"},
                    },
                }
            )
            result = subprocess.run(
                [sys.executable, "-I", material_server.__file__, str(materials), str(config)],
                input="".join(json.dumps(row) + "\n" for row in requests),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            assert result.returncode == 0, result.stderr
            replies = [json.loads(line) for line in result.stdout.splitlines()]
            assert len(replies) == 502 and replies[-1]["id"] == 501
            assert "[[RM_" in result.stdout and "合成私密姓名" not in result.stdout
            assert endpoint["token"] not in result.stdout


def test_replaced_directory_is_rejected_after_listing(tmp_path):
    """列出文件后将目录替换为外部链接，读取和后续搜索仍拒绝外部内容"""
    with access_at(tmp_path) as access:
        root = tmp_path / "first"
        folder = root / "ordinary"
        folder.mkdir()
        (folder / "main.py").write_text("safe source")
        assert access.call("list_source_files", {})["results"]
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "main.py").write_text("PRIVATE-CANARY")
        folder.rename(root / "old")
        if os.name == "nt":
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(folder), str(outside)],
                capture_output=True,
                creationflags=0x08000000,
            )
            assert result.returncode == 0
        else:
            folder.symlink_to(outside, target_is_directory=True)
        try:
            with pytest.raises(ValueError):
                access.call("read_source", {"source": "source-0", "path": "ordinary/main.py"})
            matches = pages(access, "search_sources", {"query": "PRIVATE-CANARY"})
            assert matches == []
        finally:
            folder.rmdir() if os.name == "nt" else folder.unlink()


def test_changed_file_and_mid_scan_cancellation(tmp_path, monkeypatch):
    """同轮读取使用最新内容，取消目录遍历后关闭本轮缓存"""
    from resume_maker.integrations import source_access

    with access_at(tmp_path) as access:
        cache = Path(access.directory.name)
        path = tmp_path / "first" / "main.py"
        path.write_text("before")
        args = {"source": "source-0", "path": "main.py"}
        assert access.call("read_source", args)["lines"][0]["text"] == "before"
        path.write_text("after edit")
        assert access.call("read_source", args)["lines"][0]["text"] == "after edit"

        def cancel_scan(*_):
            """在第一次返回目录进度后触发用户取消"""
            yield None
            access.cancelled.set()
            yield path

        monkeypatch.setattr(source_access, "source_paths", cancel_scan)
        with pytest.raises(Cancelled):
            access.call("search_sources", {"query": "after"})
    assert not cache.exists()
