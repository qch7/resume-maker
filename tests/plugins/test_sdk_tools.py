"""构建前身份校验和完整依赖锁不依赖开发机已有包"""

import json
from zipfile import ZipFile

import pytest

from resume_maker.plugins.tools import environment_lock, package_source
from resume_maker.runtime.graph import PluginError


def source(tmp_path, identifier="community.synthetic"):
    """独立源码只包含公开清单和最小入口"""
    root = tmp_path / "source"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "id": identifier,
                "package": identifier,
                "title": "合成插件",
                "version": "1.0.0",
                "entrypoints": {"host": {"mode": "trusted-host", "entry": "plugin.py:activate"}},
                "dependencies": ["synthetic-extra>=1"],
            }
        ),
        encoding="utf-8",
    )
    (root / "LICENSE").write_text("MIT", encoding="utf-8")
    (root / "plugin.py").write_text("raise RuntimeError('must-not-execute')", encoding="utf-8")
    return root


def wheel(directory, name, requires=()):
    """生成不需要下载或安装的 METADATA 锁验收包"""
    path = directory / f"{name.replace('-', '_')}-1.0.0-py3-none-any.whl"
    metadata = f"Name: {name}\nVersion: 1.0.0\n" + "".join(
        f"Requires-Dist: {value}\n" for value in requires
    )
    with ZipFile(path, "w") as archive:
        archive.writestr(f"{name}.dist-info/METADATA", metadata)
    return path


def test_packaging_rejects_reserved_identity_and_omits_unlisted_files(tmp_path):
    """普通检查和打包不会执行入口或收集作者的本机文件"""
    root = source(tmp_path, "provider.synthetic")
    with pytest.raises(PluginError, match="保留前缀"):
        package_source(root, tmp_path / "reserved.rmp")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["id"] = "community.synthetic"
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "private.env").write_text("synthetic-secret", encoding="utf-8")
    inspected = package_source(root, tmp_path / "valid.rmp")
    assert "private.env" not in inspected["artifacts"]
    assert inspected["dependency_plan"]["stop_host"] is True
    assert inspected["dependency_plan"]["command"][-1] == "synthetic-extra>=1"


def test_environment_lock_requires_host_and_entire_transitive_closure(tmp_path):
    """仅插件的两个库不能充当 Host 锁，补齐宿主闭包后才可生成"""
    root = source(tmp_path)
    directory = root / "wheels"
    directory.mkdir()
    wheel(directory, "synthetic-extra", ["synthetic-leaf>=1"])
    with pytest.raises(PluginError, match="resume-maker"):
        environment_lock(root, directory, root / "environment.json")
    wheel(directory, "resume-maker", ["synthetic-host-dependency==1.0.0"])
    with pytest.raises(PluginError, match="synthetic-host-dependency"):
        environment_lock(root, directory, root / "environment.json")
    wheel(directory, "synthetic-host-dependency")
    with pytest.raises(PluginError, match="synthetic-leaf"):
        environment_lock(root, directory, root / "environment.json")
    wheel(directory, "synthetic-leaf")
    lock = environment_lock(root, directory, root / "environment.json")
    assert {item["name"] for item in lock["wheels"]} == {
        "resume-maker",
        "synthetic-extra",
        "synthetic-leaf",
        "synthetic-host-dependency",
    }
    assert all(
        item["file"].startswith("wheels/") and len(item["sha256"]) == 64 for item in lock["wheels"]
    )
