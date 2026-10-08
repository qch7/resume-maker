param([string]$DataDir = '', [string]$EnvFile, [switch]$NoEnvFile, [switch]$PrintConfig)
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/'
}
& uv sync --locked --project $repoPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
. (Join-Path $PSScriptRoot 'launch-config.ps1')
$configuration = Get-LaunchConfiguration -Parameters $PSBoundParameters -RepoPath $repoPath
if ($PrintConfig) { $configuration | ConvertTo-Json -Depth 4; exit 0 }
$DataDir = $configuration.data_dir
$instancePath = Join-Path $DataDir 'instance.json'
if (-not (Test-Path -LiteralPath $instancePath)) { Write-Host 'No running instance recorded.'; exit 0 }
$instance = Get-Content -LiteralPath $instancePath -Raw | ConvertFrom-Json
# 先核对进程和随机实例标识，防止旧记录误关闭复用同一端口的其他服务
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $($instance.pid)"
if ($null -eq $process) { Write-Host 'Resume Maker is already stopped.'; exit 0 }
$health = Invoke-RestMethod -Uri "http://127.0.0.1:$($instance.port)/api/health" -TimeoutSec 3
if (-not $instance.instance_id -or $health.instance_id -ne $instance.instance_id) {
    throw 'The port belongs to another instance. It was not stopped.'
}
# 请求正常关闭，让后台队列取消并回收本次应用启动的 Codex 子进程
$tokenPage = Invoke-WebRequest -Uri "http://127.0.0.1:$($instance.port)/" -UseBasicParsing
$match = [regex]::Match($tokenPage.Content, 'name="resume-token" content="([^"]+)"')
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$($instance.port)/api/shutdown" -Headers @{'x-resume-token'=$match.Groups[1].Value} | Out-Null
Write-Host 'Resume Maker is shutting down.'
