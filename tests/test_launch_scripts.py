"""用真实 PowerShell 和合成配置验证 Windows 启停入口的一致性"""

import json
import shutil
import subprocess

import pytest

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="需要 PowerShell")


def run_powershell(script, cwd):
    """使用非交互会话运行脚本，失败时保留脱敏的合成诊断"""
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=40,
    )


@pytest.mark.parametrize("entry", ["start", "stop"])
def test_windows_scripts_resolve_same_file_and_cwd(entry, tmp_path, pytestconfig, monkeypatch):
    """启动和停止在任意工作目录读取同一文件并选取同一资料目录，诊断不启动实例"""
    root = pytestconfig.rootpath
    directory = tmp_path / "config"
    directory.mkdir()
    path = directory / "local.env"
    path.write_text(
        "RESUME_MAKER_DATA_DIR=./file-data\nRESUME_MAKER_PORT=8101\nRESUME_MAKER_OPEN_BROWSER=false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RESUME_MAKER_PORT", "8102")
    script = tmp_path / "check.ps1"
    script.write_text(
        f"& '{root}/scripts/{entry}.ps1' -EnvFile './config/local.env' -PrintConfig\n",
        encoding="utf-8",
    )
    result = run_powershell(script, tmp_path)
    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)
    assert settings["data_dir"] == str(directory / "file-data")
    assert settings["port"] == 8102 and not settings["open_browser"]
    assert not (directory / "file-data").exists()


def test_windows_helper_keeps_explicit_values_and_restores_environment(
    tmp_path, pytestconfig, monkeypatch
):
    """参数路径按调用位置解析，启动清除旧变量并在结束后恢复父环境"""
    root = pytestconfig.rootpath
    monkeypatch.setenv("RESUME_MAKER_DATA_DIR", "environment-data")
    script = tmp_path / "check.ps1"
    script.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{root}/scripts/launch-config.ps1'
$parameters = @{{DataDir='./cli-data'; Port=8103; Browser=$true; NoEnvFile=$true}}
$configuration = Get-LaunchConfiguration -Parameters $parameters -RepoPath '{root}'
$arguments = @(Get-FrozenLaunchArguments $configuration)
function uv {{
    if ($env:RESUME_MAKER_DATA_DIR) {{ throw 'Startup variable was inherited.' }}
    Write-Output 'synthetic process output'
    $global:LASTEXITCODE = 7
}}
$code = Invoke-FrozenLaunch $configuration
$result = @{{configuration=$configuration; arguments=$arguments; code=$code}}
$result.restored = $env:RESUME_MAKER_DATA_DIR
$result | ConvertTo-Json -Depth 5
""",
        encoding="utf-8",
    )
    result = run_powershell(script, tmp_path)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout[result.stdout.index("{") :])
    assert value["configuration"]["data_dir"] == str(tmp_path / "cli-data")
    assert value["configuration"]["port"] == 8103
    assert value["configuration"]["open_browser"]
    assert "--no-env-file" in value["arguments"]
    assert "--frontend-dir" not in value["arguments"]
    assert value["code"] == 7 and value["restored"] == "environment-data"


def test_windows_helper_rejects_conflicting_switches(tmp_path, pytestconfig):
    """互斥浏览器及文件选项不能被启动器静默忽略"""
    script = tmp_path / "check.ps1"
    script.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{pytestconfig.rootpath}/scripts/launch-config.ps1'
$parameters = @{{Browser=$true; NoBrowser=$true}}
Get-LaunchConfiguration -Parameters $parameters -RepoPath '{pytestconfig.rootpath}'
""",
        encoding="utf-8",
    )
    result = run_powershell(script, tmp_path)
    assert result.returncode != 0
    assert "Choose either -Browser or -NoBrowser" in result.stderr
