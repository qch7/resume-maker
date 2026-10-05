"""联合依赖环境的真实离线安装及冲突行为"""

import hashlib
import json
from zipfile import ZipFile

import pytest

from resume_maker.infrastructure.execution import Execution, Sandbox
from resume_maker.integrations.providers.process import execute
from resume_maker.integrations.providers.sandbox import LocalSandbox
from resume_maker.runtime.environments import EnvironmentStore
from resume_maker.runtime.graph import PluginError
from resume_maker.sdk.manifest import Manifest


def locked_plugin(directory, owner, dependency, version="1.0.0"):
    """提供完整合成 wheel 锁，测试不连接包索引或修改宿主环境"""
    directory.mkdir()
    wheels = []
    for name, value in [("resume-maker", "0.1.0"), (dependency, version)]:
        normalized = name.replace("-", "_")
        path = directory / f"{normalized}-{value}-py3-none-any.whl"
        with ZipFile(path, "w") as archive:
            for filename, content in {
                f"{normalized}.py": "VALUE = 42\n",
                f"{normalized}-{value}.dist-info/METADATA": (
                    f"Metadata-Version: 2.1\nName: {name}\nVersion: {value}\n"
                ),
                f"{normalized}-{value}.dist-info/WHEEL": (
                    "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
                ),
                f"{normalized}-{value}.dist-info/RECORD": "",
            }.items():
                # 时间固定保证两包相同 wheel 的字节摘要一致
                from zipfile import ZipInfo

                archive.writestr(ZipInfo(filename), content)
        wheels.append(
            {
                "name": name,
                "version": value,
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    (directory / "lock.json").write_text(json.dumps({"version": 1, "wheels": wheels}))
    return Manifest(
        id=owner,
        title=owner,
        version="1.0.0",
        package=owner,
        dependencies=[f"{dependency}=={version}"],
        environment_lock="lock.json",
        entrypoints={"host": {"mode": "trusted-host", "entry": "plugin:activate"}},
    )


def test_cohort_installs_union_without_publishing_active_index(tmp_path):
    """实际新解释器同时导入两份插件的固定依赖，成功前不改正式环境索引"""
    first = locked_plugin(tmp_path / "first", "community.first", "synthetic-one")
    second = locked_plugin(tmp_path / "second", "community.second", "synthetic-two")
    store = EnvironmentStore(tmp_path / "data")
    execution = Execution(execute)
    sandbox = Sandbox(execution, LocalSandbox())
    result = store.prepare_host(
        [(first, tmp_path / "first"), (second, tmp_path / "second")],
        execution,
        sandbox,
        [first, second],
    )
    assert result["state"] == "ready"
    assert store.records() == {}
    command = [
        result["python"],
        "-I",
        "-c",
        "import synthetic_one,synthetic_two; print(synthetic_one.VALUE+synthetic_two.VALUE)",
    ]
    from resume_maker.runtime.upgrades import process_environment

    environment = process_environment()
    grant = sandbox.authorize(
        "sys.plugins",
        "plugin.candidate",
        1,
        ["process_cleanup"],
        command=command,
        cwd=tmp_path,
        env=environment,
    )
    import threading

    assert (
        execution.execute(
            grant, command, cwd=tmp_path, env=environment, timeout=10, cancelled=threading.Event()
        ).strip()
        == "84"
    )


def test_cohort_rejects_conflicting_fixed_dependency_before_install(tmp_path):
    """两个包要求同名不同版本时立即拒绝，不准备半份共享环境"""
    first = locked_plugin(tmp_path / "first", "community.first", "synthetic-one")
    second = locked_plugin(tmp_path / "second", "community.second", "synthetic-one", "2.0.0")
    store = EnvironmentStore(tmp_path / "data")
    with pytest.raises(PluginError, match="冲突"):
        store.prepare_host(
            [(first, tmp_path / "first"), (second, tmp_path / "second")],
            None,
            None,
            [first, second],
        )
    assert not store.root.exists() and store.records() == {}
