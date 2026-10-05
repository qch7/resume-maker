"""发行插件的目录发现、客户端资源和私有边界回归"""

import hashlib
import json
import sys

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.plugins import client_assets, discovery
from resume_maker.runtime.graph import PluginError


def test_discovery_does_not_import_code_and_uses_package_memberships(tmp_path, monkeypatch):
    """组合归属随包消失，读取清单不执行任意入口代码"""
    directory = tmp_path / "community_example"
    directory.mkdir()
    (directory / "entry.py").write_text("raise RuntimeError('must not execute')", encoding="utf-8")
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "id": "community.example",
                "version": "1.0.0",
                "package": "example",
                "title": "示例",
                "entrypoints": {},
            }
        ),
        encoding="utf-8",
    )
    (directory / "package.json").write_text(
        json.dumps({"resumeMaker": {"profiles": ["standard"]}}),
        encoding="utf-8",
    )
    policy = tmp_path / "policy"
    policy.mkdir()
    (policy / "profiles.json").write_text(
        json.dumps({"required": [], "profiles": {"standard": [], "minimal": []}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(discovery, "ROOT", policy)
    monkeypatch.setattr(discovery, "PACKAGES", tmp_path)
    _, selected, _ = discovery.selection("standard")
    assert selected == {"community.example"}
    assert not any(name.endswith("community_example.entry") for name in sys.modules)
    directory.rename(tmp_path / "removed")
    # 移出的目录也需退出扫描根，否则它仍属于已安装代码包
    (tmp_path / "removed").rename(policy / "removed")
    assert discovery.selection("standard")[1] == set()


def test_missing_required_package_is_reported_before_code_import(tmp_path, monkeypatch):
    """删除必需系统包明确拒绝启动，不能伪装成可选能力缺失"""
    monkeypatch.setattr(discovery, "PACKAGES", tmp_path)
    with pytest.raises(PluginError, match="缺少必需插件"):
        discovery.discover()


def test_bundled_client_resources_are_selected_indexed_and_verified(tmp_path, monkeypatch):
    """资源仅限活动插件构建索引，摘要变化和源码下载均被拒绝"""
    output = tmp_path / "output"
    output.mkdir()
    content = b"export function activate(context) {}"
    (output / "plugin.js").write_bytes(content)
    (output / "private.js").write_text("private", encoding="utf-8")
    (output / "artifacts.json").write_text(
        json.dumps({"plugin.js": hashlib.sha256(content).hexdigest()}),
        encoding="utf-8",
    )
    monkeypatch.setattr(client_assets, "client_directory", lambda _id: output)
    headers = {"x-resume-token": "synthetic"}
    with TestClient(create_app(Config(data_dir=tmp_path / "data", token="synthetic"))) as client:
        capabilities = client.get("/api/capabilities", headers=headers).json()
        descriptor = next(
            item for item in capabilities["client"] if item["id"] == "ext.activity-ui"
        )
        url = descriptor["entry"]["entry"]
        assert url.startswith("/bundled-plugin-assets/ext.activity-ui/")
        assert client.get(url).content == content
        assert client.get(url.replace("plugin.js", "private.js")).status_code == 404
        assert client.get(url.replace("plugin.js", "manifest.json")).status_code == 404
        (output / "plugin.js").write_bytes(b"changed")
        assert client.get(url).status_code == 409
    with TestClient(create_app(Config(data_dir=tmp_path / "minimal", profile="minimal"))) as client:
        assert client.get(url).status_code == 404
