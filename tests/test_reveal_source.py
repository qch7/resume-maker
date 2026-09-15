"""验证来源定位的项目归属、历史快照映射及文件管理器调用。"""

from pathlib import Path

import pytest
from conftest import record_source_files
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.integrations import desktop
from resume_maker.services.projects import Projects


def test_reveal_uses_snapshot_root_after_sources_reordered(catalog, project, tmp_path, monkeypatch):
    """来源顺序改变后仍打开引文原始仓库，并保留含中文和空格的完整文件名。"""
    original = Path(project["roots"][0]) / "引用 文件.py"
    original.write_text("print('source')", encoding="utf-8")
    snapshot = record_source_files(catalog.db, tmp_path / "data", project, (original.name,))
    other = tmp_path / "other"
    other.mkdir()
    projects = Projects(catalog)
    projects.update_sources(project["id"], project["name"], [str(other), *project["roots"]])
    opened = []
    monkeypatch.setattr("resume_maker.services.projects.reveal_file", opened.append)
    projects.reveal_source(project["id"], snapshot["id"], "source-0", original.name)
    assert opened == [original.resolve()]


def test_reveal_endpoint_checks_token_and_snapshot_ownership(tmp_path, monkeypatch):
    """只有带实例令牌的本项目快照引用能触发文件管理器。"""
    app = create_app(Config(data_dir=tmp_path / "data", token="test-token"))
    services = app.state.services
    roots = [tmp_path / "source", tmp_path / "other"]
    for root in roots:
        root.mkdir()
        (root / "README.md").write_text("# Source", encoding="utf-8")
    project, other = [services.catalog.create_project(p.name, [str(p)]) for p in roots]
    snapshot = record_source_files(services.db, tmp_path / "data", project)
    body = {"snapshot_id": snapshot["id"], "source": "source-0", "path": "README.md"}
    opened = []
    monkeypatch.setattr("resume_maker.services.projects.reveal_file", opened.append)
    headers = {"x-resume-token": "test-token"}
    with TestClient(app) as client:
        url = f"/api/projects/{project['id']}/sources/reveal"
        assert client.post(url, json=body).status_code == 401
        assert (
            client.post(
                f"/api/projects/{other['id']}/sources/reveal", json=body, headers=headers
            ).status_code
            == 404
        )
        assert opened == []
        response = client.post(url, json=body, headers=headers)
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert opened == [(roots[0] / "README.md").resolve()]


@pytest.mark.parametrize(
    "path",
    [
        "../outside.txt",
        "..\\outside.txt",
        "/etc/hosts",
        "C:\\secret.txt",
        "README.md:stream",
        "unknown.py",
    ],
)
def test_reveal_rejects_unlisted_or_escaping_paths(catalog, project, tmp_path, monkeypatch, path):
    """越界、绝对路径、备用数据流和快照外文件均不能触发本机打开。"""
    snapshot = record_source_files(catalog.db, tmp_path / "data", project)
    opened = []
    monkeypatch.setattr("resume_maker.services.projects.reveal_file", opened.append)
    with pytest.raises(Problem):
        Projects(catalog).reveal_source(project["id"], snapshot["id"], "source-0", path)
    assert opened == []


def test_reveal_reports_missing_source_file(catalog, project, tmp_path, monkeypatch):
    """文件移走后报告明确错误，不退回其他同名仓库或打开不存在的位置。"""
    snapshot = record_source_files(catalog.db, tmp_path / "data", project)
    (Path(project["roots"][0]) / "README.md").unlink()
    opened = []
    monkeypatch.setattr("resume_maker.services.projects.reveal_file", opened.append)
    with pytest.raises(Problem, match="来源文件已移动或不存在"):
        Projects(catalog).reveal_source(project["id"], snapshot["id"], "source-0", "README.md")
    assert opened == []


@pytest.mark.parametrize(
    "platform,command",
    [("win32", ["explorer.exe", "/select,"]), ("darwin", ["open", "-R"]), ("linux", ["xdg-open"])],
)
def test_file_manager_keeps_paths_as_single_arguments(tmp_path, monkeypatch, platform, command):
    """各平台通过参数数组调用文件管理器，含空格的文件路径不会作为命令解析。"""
    path = tmp_path / "源码 文件.py"
    calls = []
    monkeypatch.setattr(desktop.sys, "platform", platform)
    monkeypatch.setattr(desktop.subprocess, "Popen", calls.append)
    desktop.reveal_file(path)
    assert calls == [[*command, str(path.parent if platform == "linux" else path)]]


def test_file_manager_launch_error_is_actionable(tmp_path, monkeypatch):
    """文件管理器不可用时将系统错误转换为可在引用弹窗内显示的提示。"""

    def unavailable(command):
        """模拟缺少桌面文件管理器的运行环境。"""
        raise FileNotFoundError("missing")

    monkeypatch.setattr(desktop.subprocess, "Popen", unavailable)
    with pytest.raises(Problem, match="无法启动资源管理器"):
        desktop.reveal_file(tmp_path / "README.md")
