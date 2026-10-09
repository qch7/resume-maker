"""使用模拟对话框验证路径选择的鉴权、取消、互斥和错误恢复"""

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.integrations import path_picker


def test_path_picker_endpoint_requires_token_and_valid_kind(tmp_path, monkeypatch):
    """未授权或未知类型请求不能打开系统窗口，选定路径及取消结果原样返回"""
    calls = []
    selected = str(tmp_path / "中文 简历.docx")

    def choose(kind, initial):
        """记录选择请求，第二次模拟用户取消"""
        calls.append((kind, initial))
        return selected if len(calls) == 1 else None

    monkeypatch.setattr("resume_maker.api.routes.system.pick_path", choose)
    with TestClient(create_app(Config(data_dir=tmp_path / "data", token="picker-test"))) as client:
        payload = {"kind": "docx", "initial_path": str(tmp_path)}
        headers = {"x-resume-token": "picker-test"}
        assert client.post("/api/paths/pick", json=payload).status_code == 401
        assert (
            client.post(
                "/api/paths/pick",
                json=payload,
                headers={**headers, "origin": "https://example.test"},
            ).status_code
            == 403
        )
        assert (
            client.post("/api/paths/pick", json={"kind": "shell"}, headers=headers).status_code
            == 422
        )
        assert calls == []
        assert client.post("/api/paths/pick", json=payload, headers=headers).json() == {
            "path": selected
        }
        assert client.post("/api/paths/pick", json=payload, headers=headers).json() == {
            "path": None
        }
        assert calls == [("docx", str(tmp_path)), ("docx", str(tmp_path))]


def test_initial_directory_uses_file_parent_and_resolves_executable(tmp_path, monkeypatch):
    """现有文件、目录和 PATH 中的可执行文件都能提供正确的初始浏览位置"""
    file = tmp_path / "简历 文档.docx"
    file.write_bytes(b"path only")
    monkeypatch.chdir(tmp_path)
    assert path_picker.initial_directory(str(tmp_path), "folder") == tmp_path.resolve()
    assert path_picker.initial_directory(f'"{file}"', "docx") == tmp_path.resolve()
    assert path_picker.initial_directory(file.name, "docx") == tmp_path.resolve()
    assert (
        path_picker.initial_directory(str(tmp_path / "尚未存在.docx"), "docx") == tmp_path.resolve()
    )
    monkeypatch.setattr(path_picker.shutil, "which", lambda _: str(file))
    assert path_picker.initial_directory("codex", "executable") == tmp_path.resolve()
    assert path_picker.initial_directory("", "docx") == Path.home()


def test_only_one_dialog_opens_and_cancel_releases_slot(tmp_path, monkeypatch):
    """并行点击只打开一个窗口且取消后允许再次选择"""
    monkeypatch.setattr(path_picker.sys, "platform", "win32")
    started, release = threading.Event(), threading.Event()
    results = []

    def dialog(_kind, _directory):
        """用事件代表尚未关闭的原生选择窗口"""
        started.set()
        assert release.wait(3)
        return None

    def first():
        """记录首次选择的取消结果"""
        results.append(path_picker.pick_path("folder", str(tmp_path)))

    monkeypatch.setattr(path_picker, "_windows_dialog", dialog)
    thread = threading.Thread(target=first)
    thread.start()
    try:
        assert started.wait(2)
        with pytest.raises(Problem, match="已有文件选择窗口") as exc:
            path_picker.pick_path("docx")
        assert exc.value.status == 409
    finally:
        release.set()
        thread.join(timeout=3)
    assert results == [None] and not thread.is_alive()
    assert path_picker.pick_path("folder", str(tmp_path)) is None


def test_dialog_failure_releases_slot_and_other_platforms_remain_usable(monkeypatch):
    """系统错误转换为可操作提示，失败后不会阻塞下一次选择或手动填写"""
    monkeypatch.setattr(path_picker.sys, "platform", "win32")

    def unavailable(*_args):
        """模拟当前进程没有可用的 Windows 桌面"""
        raise OSError("No desktop")

    monkeypatch.setattr(path_picker, "_windows_dialog", unavailable)
    with pytest.raises(Problem, match="无法打开"):
        path_picker.pick_path("docx")
    monkeypatch.setattr(path_picker, "_windows_dialog", lambda *_: None)
    assert path_picker.pick_path("docx") is None
    monkeypatch.setattr(path_picker.sys, "platform", "linux")
    with pytest.raises(Problem, match="手动填写") as exc:
        path_picker.pick_path("folder")
    assert exc.value.status == 501
