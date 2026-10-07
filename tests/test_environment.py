"""验证启动配置优先级、文件边界和不包含凭据的诊断"""

import json
import os

import pytest

from resume_maker import cli
from resume_maker.core import config
from resume_maker.core.environment import (
    LAUNCH_VARIABLES,
    LaunchConfigurationError,
    resolve_launch,
)


def test_precedence_paths_and_empty_overrides(tmp_path):
    """各字段独立覆盖，文件路径相对文件位置，环境和参数相对启动位置"""
    directory = tmp_path / "configuration"
    directory.mkdir()
    env_file = directory / ".env"
    env_file.write_text(
        "RESUME_MAKER_PORT=8001\nRESUME_MAKER_DATA_DIR=./file-data\n"
        "RESUME_MAKER_FRONTEND_DIR=./web\nRESUME_MAKER_PROFILE=minimal\n"
        "RESUME_MAKER_PLUGIN_CONFIG=./plugins.json\nRESUME_MAKER_OPEN_BROWSER=false\n",
        encoding="utf-8",
    )
    resolved = resolve_launch(
        env_file=env_file,
        environment={"resume_maker_port": "8002", "RESUME_MAKER_DATA_DIR": "env-data"},
        overrides={"port": 8003, "profile": "", "open_browser": True},
        cwd=tmp_path,
    )
    assert resolved.settings.port == 8003
    assert resolved.settings.data_dir == tmp_path / "env-data"
    assert resolved.settings.frontend_dir == directory / "web"
    assert resolved.settings.plugin_config == directory / "plugins.json"
    assert resolved.settings.profile is None
    assert resolved.settings.open_browser
    assert resolved.sources["port"] == "cli"
    assert resolved.sources["data_dir"] == "environment"
    assert resolved.sources["frontend_dir"] == "env_file"


@pytest.mark.parametrize("value", ["0", "65536", "2.5", "secret-value", True, 2.5, ""])
def test_invalid_port_has_safe_diagnostic(value):
    """启动前拒绝端口范围和类型错误，诊断不回显输入"""
    with pytest.raises(LaunchConfigurationError) as caught:
        resolve_launch(environment={}, overrides={"port": value})
    assert "RESUME_MAKER_PORT (cli)" in str(caught.value)
    assert "secret-value" not in str(caught.value)


@pytest.mark.parametrize(
    "value, expected", [("YES", True), ("off", False), ("1", True), ("0", False)]
)
def test_browser_values(value, expected):
    """跨平台布尔输入明确决定是否打开浏览器"""
    assert (
        resolve_launch(environment={"RESUME_MAKER_OPEN_BROWSER": value}).settings.open_browser
        is expected
    )


@pytest.mark.parametrize("field, value", [("OPEN_BROWSER", "maybe"), ("PROFILE", "typo")])
def test_invalid_choices(field, value):
    """布尔和组合拼写错误在读取资料前报告"""
    with pytest.raises(LaunchConfigurationError, match=field):
        resolve_launch(environment={"RESUME_MAKER_" + field: value})


def test_dotenv_syntax_does_not_mutate_environment(tmp_path):
    """接受 BOM、export、引号和注释，保持所有进程环境值不变"""
    path = tmp_path / ".env"
    path.write_text(
        '\ufeff# local configuration\nexport RESUME_MAKER_PORT="8012" # comment\n'
        "RESUME_MAKER_DATA_DIR='folder with spaces'\nRESUME_MAKER_PROFILE=\n",
        encoding="utf-8",
    )
    before = dict(os.environ)
    settings = resolve_launch(env_file=path, environment={}).settings
    assert settings.port == 8012
    assert settings.data_dir == tmp_path / "folder with spaces"
    assert settings.profile is None
    assert dict(os.environ) == before


@pytest.mark.parametrize(
    "source",
    [
        "OPENAI_API_KEY=secret-value\n",
        "RESUME_MAKER_TOKEN=secret-value\n",
        "RESUME_MAKER_PORT=8000\nRESUME_MAKER_PORT=8001\n",
        "RESUME_MAKER_DATA_DIR\n",
        "RESUME_MAKER_DATA_DIR=${HOME}\n",
        'RESUME_MAKER_DATA_DIR="secret-value\n',
    ],
)
def test_invalid_file_is_rejected_without_values(tmp_path, source):
    """错误语法、未知变量、重复项和插值均给出不含凭据的行号诊断"""
    path = tmp_path / ".env"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(LaunchConfigurationError) as caught:
        resolve_launch(env_file=path, environment={})
    assert "行" in str(caught.value)
    assert "secret-value" not in str(caught.value)


def test_missing_or_non_utf8_file(tmp_path):
    """显式文件不存在或编码错误均清楚报告，不能静默回退"""
    path = tmp_path / ".env"
    with pytest.raises(LaunchConfigurationError, match="UTF-8"):
        resolve_launch(env_file=path, environment={})
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(LaunchConfigurationError, match="UTF-8"):
        resolve_launch(env_file=path, environment={})


def test_unknown_and_conflicting_environment_names():
    """系统及供应商变量可保留，应用前缀错拼和冲突的大小写定义须拒绝"""
    assert resolve_launch(environment={"OPENAI_API_KEY": "secret-value"}).settings.port == 8765
    with pytest.raises(LaunchConfigurationError, match="未知启动变量"):
        resolve_launch(environment={"RESUME_MAKER_POTR": "8001"})
    with pytest.raises(LaunchConfigurationError, match="大小写"):
        resolve_launch(environment={"resume_maker_port": "8001", "RESUME_MAKER_PORT": "8002"})


def test_cli_print_configuration_and_overrides(tmp_path, monkeypatch, capsys):
    """诊断只输出声明字段及来源，不启动服务、打开浏览器或创建资料目录"""
    path = tmp_path / ".env"
    path.write_text("RESUME_MAKER_PORT=8001\nRESUME_MAKER_OPEN_BROWSER=false\n", encoding="utf-8")
    monkeypatch.setenv("RESUME_MAKER_PORT", "8002")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    data = tmp_path / "new-data"
    cli.main(
        [
            "--print-config",
            "--env-file",
            str(path),
            "--port",
            "8003",
            "--browser",
            "--data-dir",
            str(data),
        ]
    )
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["port"] == 8003 and result["open_browser"]
    assert result["data_dir"] == str(data)
    assert result["sources"]["port"] == "cli"
    assert set(result) == set(LAUNCH_VARIABLES.values()) | {
        "env_file",
        "sources",
        "frontend_override",
    }
    assert "secret-value" not in output
    assert not data.exists()


def test_source_file_discovery_and_disable(tmp_path, monkeypatch, capsys):
    """源码只发现自身根目录的文件，关闭文件加载后保留进程环境覆盖"""
    project = tmp_path / "source"
    project.mkdir()
    (project / "pyproject.toml").touch()
    path = project / ".env"
    path.write_text("RESUME_MAKER_PORT=8001\n", encoding="utf-8")
    monkeypatch.setattr(config, "__file__", str(project / "src/resume_maker/core/config.py"))
    monkeypatch.chdir(tmp_path)
    assert config.default_env_file() == path
    monkeypatch.setattr(cli, "default_env_file", config.default_env_file)
    cli.main(["--print-config"])
    assert json.loads(capsys.readouterr().out)["port"] == 8001
    cli.main(["--print-config", "--no-env-file"])
    assert json.loads(capsys.readouterr().out)["port"] == 8765
    monkeypatch.setattr(
        config, "__file__", str(tmp_path / "site-packages/resume_maker/core/config.py")
    )
    assert config.default_env_file() is None


def test_high_priority_value_replaces_invalid_lower_value(tmp_path):
    """校验最终有效值，低优先级字段被覆盖后不阻碍启动"""
    path = tmp_path / ".env"
    path.write_text("RESUME_MAKER_PORT=invalid\n", encoding="utf-8")
    assert (
        resolve_launch(env_file=path, environment={}, overrides={"port": 8000}).settings.port
        == 8000
    )


def test_example_and_documentation_cover_the_declared_variables(pytestconfig):
    """示例和公开文档覆盖全部声明字段，默认示例可以直接解析"""
    root = pytestconfig.rootpath
    example = root / ".env.example"
    declared = {
        line.split("=", 1)[0]
        for line in example.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    assert declared == set(LAUNCH_VARIABLES)
    settings = resolve_launch(env_file=example, environment={}).settings
    assert settings.port == 8765 and settings.profile is None
    documentation = (root / "docs/reference/configuration.md").read_text(encoding="utf-8")
    assert all(f"`{name}`" in documentation for name in declared)


@pytest.mark.parametrize("option", ["--port", "--profile"])
def test_cli_invalid_value_is_validated_without_echo(option, capsys):
    """命令行同样使用统一校验，不由参数解析器回显可能误填的凭据"""
    with pytest.raises(SystemExit) as caught:
        cli.main(["--no-env-file", "--print-config", option, "secret-value"])
    assert caught.value.code == 2
    assert "secret-value" not in capsys.readouterr().err
