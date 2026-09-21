param(
    [int]$Port = 8765,
    [string]$DataDir = '',
    [switch]$Rebuild,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoPath
if (-not $DataDir) {
    $DataDir = if ($env:RESUME_MAKER_DATA_DIR) { $env:RESUME_MAKER_DATA_DIR } else { Join-Path $repoPath 'data' }
}
$DataDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DataDir)
$url = "http://127.0.0.1:$Port"
# 仅复用目标数据目录登记的实例，避免迁移目录后仍打开旧数据库
$health = $null
try {
    $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2
} catch {}
if ($health.status -eq 'ok') {
    $instancePath = Join-Path $DataDir 'instance.json'
    $instance = if (Test-Path -LiteralPath $instancePath) { Get-Content -LiteralPath $instancePath -Raw | ConvertFrom-Json } else { $null }
    if ($instance.instance_id -and $instance.instance_id -eq $health.instance_id -and $instance.port -eq $Port) {
        if (-not $NoBrowser) { Start-Process $url }
        Write-Host "Resume Maker is already running at $url"
        exit 0
    }
    throw "Port $Port is used by a different Resume Maker data directory. Stop that instance or choose another -Port."
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/'
}
& uv sync --locked
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$indexPath = Join-Path $repoPath 'frontend/dist/index.html'
$needsBuild = $Rebuild -or -not (Test-Path -LiteralPath $indexPath)
if (-not $needsBuild) {
    $builtAt = (Get-Item -LiteralPath $indexPath).LastWriteTimeUtc
    # 构建配置、依赖锁和入口 HTML 的变化同样要求重建，不能只比较组件源码
    $buildInputs = @(Get-ChildItem -LiteralPath (Join-Path $repoPath 'frontend/src') -File -Recurse)
    foreach ($relative in @('package.json', 'package-lock.json', 'vite.config.ts', 'tsconfig.json', 'index.html')) {
        $buildInputs += Get-Item -LiteralPath (Join-Path $repoPath "frontend/$relative")
    }
    $newer = $buildInputs | Where-Object { $_.LastWriteTimeUtc -gt $builtAt } | Select-Object -First 1
    $needsBuild = $null -ne $newer
}
if ($needsBuild) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22 LTS first.' }
    # 每次重建先按锁文件安装，拉取新依赖后不会继续使用旧 node_modules
    & npm --prefix frontend ci
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & npm --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$launchArgs = @('run', '--no-sync', 'python', '-m', 'resume_maker.cli', '--port', "$Port", '--data-dir', $DataDir)
# 前台运行让终端关闭行为和 CLI 正常退出保持一致
if ($NoBrowser) { $launchArgs += '--no-browser' }
& uv @launchArgs
exit $LASTEXITCODE
