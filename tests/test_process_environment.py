"""验证启动配置冻结和不同子进程职责的环境继承边界"""

import argparse
import sys
import threading
from types import SimpleNamespace

import pytest

from resume_maker.cli import add_launch_arguments, configured_launch
from resume_maker.core.environment import resolve_launch
from resume_maker.core.process_environment import EnvironmentPolicy, process_environment
from resume_maker.host_supervisor import host_command
from resume_maker.integrations import desktop, sources
from resume_maker.integrations.providers.process import execute
from resume_maker.plugin_packages.ext_word.integrations.word.controlled import ControlledWord
from resume_maker.sdk.model import Cancelled


def test_unbounded_process_execution_still_observes_cancellation(tmp_path):
    """无限期服务执行依然检查取消并回收本轮进程"""
    flag = threading.Event()

    def event(value):
        """子进程确认启动后才请求取消，避免只测试执行前检查"""
        if value.get("ready"):
            flag.set()

    with pytest.raises(Cancelled):
        execute(
            [
                sys.executable,
                "-c",
                "import time; print('{\"ready\":true}', flush=True); time.sleep(30)",
            ],
            cwd=tmp_path,
            env=process_environment(EnvironmentPolicy.CANDIDATE),
            timeout=None,
            cancelled=flag,
            event=event,
        )


@pytest.mark.parametrize(
    "policy",
    [
        EnvironmentPolicy.CANDIDATE,
        EnvironmentPolicy.WORKER,
        EnvironmentPolicy.DESKTOP,
        EnvironmentPolicy.MODEL,
    ],
)
def test_restricted_processes_do_not_inherit_credentials(policy):
    """候选、worker、Word 和连接的基础环境均排除应用配置及任意供应商凭据"""
    source = {
        "Path": "/synthetic/bin",
        "SystemRoot": "/synthetic/windows",
        "SYNTHETIC_PROVIDER_KEY": "secret-value",
        "OPENAI_API_KEY": "secret-value",
        "CODEX_HOME": "/personal/home",
        "RESUME_MAKER_PORT": "8000",
        "PYTHONPATH": "/personal/python",
        "TEMP": "/system/temp",
        "HTTP_PROXY": "http://proxy",
    }
    actual = process_environment(policy, source)
    assert actual["Path"] == source["Path"] and actual["SystemRoot"] == source["SystemRoot"]
    assert not set(actual) & {
        "SYNTHETIC_PROVIDER_KEY",
        "OPENAI_API_KEY",
        "CODEX_HOME",
        "RESUME_MAKER_PORT",
        "PYTHONPATH",
    }
    assert ("HTTP_PROXY" in actual) == (policy == EnvironmentPolicy.MODEL)
    assert ("TEMP" in actual) == (policy != EnvironmentPolicy.WORKER)
    assert source["OPENAI_API_KEY"] == "secret-value"


def test_host_preserves_arbitrary_provider_inputs_but_clears_launch_values():
    """正式宿主可以按配置借用任意命名的供应商密钥，启动字段统一由参数传递"""
    actual = process_environment(
        EnvironmentPolicy.HOST,
        {
            "SYNTHETIC_PROVIDER_KEY": "secret-value",
            "CODEX_HOME": "/personal/home",
            "resume_maker_profile": "minimal",
            "RESUME_MAKER_PROVIDER_KEY": "stale-secret",
        },
    )
    assert actual == {"SYNTHETIC_PROVIDER_KEY": "secret-value", "CODEX_HOME": "/personal/home"}


def test_supervised_children_freeze_launch_values_and_keep_persisted_selection(
    tmp_path, monkeypatch
):
    """文件和环境变更不影响子宿主，重启只恢复已保存组合，前端覆盖继续生效"""
    path = tmp_path / ".env"
    path.write_text(
        "RESUME_MAKER_PORT=8011\nRESUME_MAKER_PROFILE=minimal\n"
        "RESUME_MAKER_DATA_DIR=./data\nRESUME_MAKER_FRONTEND_DIR=./web\n"
        "RESUME_MAKER_PLUGIN_CONFIG=./plugins.json\nRESUME_MAKER_OPEN_BROWSER=false\n"
        "RESUME_MAKER_STARTUP_TIMEOUT_SECONDS=180\n"
        "RESUME_MAKER_HEALTH_OBSERVATION_SECONDS=5\nRESUME_MAKER_HEALTH_POLL_SECONDS=1.5\n",
        encoding="utf-8",
    )
    parser = argparse.ArgumentParser()
    add_launch_arguments(parser)
    args = parser.parse_args(["--env-file", str(path)])
    config, _ = configured_launch(args)
    path.write_text("RESUME_MAKER_PORT=8012\nRESUME_MAKER_PROFILE=standard\n", encoding="utf-8")
    monkeypatch.setenv("RESUME_MAKER_PORT", "8013")
    for first, candidate in [(True, False), (False, False), (True, True)]:
        command = host_command("python", config.data_dir, args, first=first, candidate=candidate)
        parsed = parser.parse_args(command[7:])
        assert parsed.no_env_file
        overrides = {
            key: getattr(parsed, key)
            for key in (
                "port",
                "data_dir",
                "frontend_dir",
                "profile",
                "plugin_config",
                "open_browser",
                "startup_timeout_seconds",
                "health_observation_seconds",
                "health_poll_seconds",
            )
            if getattr(parsed, key) is not None
        }
        settings = resolve_launch(
            environment=process_environment(EnvironmentPolicy.HOST), overrides=overrides
        ).settings
        assert settings.port == 8011 and settings.data_dir == tmp_path / "data"
        assert settings.frontend_dir == tmp_path / "web" and not settings.open_browser
        assert settings.startup_timeout_seconds == config.supervisor.startup_timeout_seconds == 180
        assert settings.health_observation_seconds == 5 and settings.health_poll_seconds == 1.5
        assert (settings.profile == "minimal") == (first and not candidate)
        assert (settings.plugin_config == tmp_path / "plugins.json") == (first and not candidate)


def test_upgrade_uses_new_wheel_frontend_when_no_override(tmp_path):
    """未显式覆盖资源目录时，新解释器自行选取其安装包资源"""
    parser = argparse.ArgumentParser()
    add_launch_arguments(parser)
    args = parser.parse_args(["--no-env-file"])
    config, _ = configured_launch(args)
    command = host_command("new-python", tmp_path, args, first=False, candidate=True)
    assert "--frontend-dir" not in command
    assert config.frontend is not None


def test_actual_process_callers_use_role_environment(tmp_path, monkeypatch):
    """Git、桌面定位和受管 Word 的真实调用入口均使用职责环境，不传供应商密钥"""
    monkeypatch.setenv("SYNTHETIC_PROVIDER_KEY", "secret-value")
    monkeypatch.setenv("DISPLAY", ":synthetic")
    captured = []

    def run(*args, **kwargs):
        """记录真实调用参数，返回合成进程结果"""
        captured.append(kwargs["env"])
        return SimpleNamespace(stdout="synthetic", returncode=0)

    monkeypatch.setattr(sources.subprocess, "run", run)
    monkeypatch.setattr(desktop.subprocess, "Popen", run)
    assert sources.git(tmp_path, "status", "--short") == "synthetic"
    desktop.reveal_file(tmp_path / "source.py")
    execution = SimpleNamespace(execute=run, revoke=lambda *_: None)
    sandbox = SimpleNamespace(authorize=lambda *_, **__: "synthetic-grant")
    word = ControlledWord(execution, sandbox, 1)
    word.execute(["synthetic-word"], cwd=tmp_path, timeout=1)
    word.close()
    assert len(captured) == 3
    assert all("SYNTHETIC_PROVIDER_KEY" not in value for value in captured)
    assert "DISPLAY" not in captured[0]
    assert all(value["DISPLAY"] == ":synthetic" for value in captured[1:])
