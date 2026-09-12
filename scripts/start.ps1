param(
    [int]$Port = 8765,
    [string]$DataDir = '',
    [switch]$Rebuild,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoPath
$url = "http://127.0.0.1:$Port"
# 默认启动复用返回健康状态的本机服务，自定义数据目录仍交由 CLI 独立校验。
try {
    $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2
    if ($health.status -eq 'ok' -and -not $DataDir) {
        if (-not $NoBrowser) { Start-Process $url }
        Write-Host "Resume Maker is already running at $url"
        exit 0
    }
} catch {}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/'
}
& uv sync --locked
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$indexPath = Join-Path $repoPath 'frontend/dist/index.html'
$needsBuild = $Rebuild -or -not (Test-Path -LiteralPath $indexPath)
if (-not $needsBuild) {
    $builtAt = (Get-Item -LiteralPath $indexPath).LastWriteTimeUtc
    # 构建配置、依赖锁和入口 HTML 的变化同样要求重建，不能只比较组件源码。
    $buildInputs = @(Get-ChildItem -LiteralPath (Join-Path $repoPath 'frontend/src') -File -Recurse)
    foreach ($relative in @('package.json', 'package-lock.json', 'vite.config.ts', 'tsconfig.json', 'index.html')) {
        $buildInputs += Get-Item -LiteralPath (Join-Path $repoPath "frontend/$relative")
    }
    $newer = $buildInputs | Where-Object { $_.LastWriteTimeUtc -gt $builtAt } | Select-Object -First 1
    $needsBuild = $null -ne $newer
}
if ($needsBuild) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22 LTS first.' }
    # 每次重建先按锁文件安装，拉取新依赖后不会继续使用旧 node_modules。
    & npm --prefix frontend ci
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & npm --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$launchArgs = @('run', '--no-sync', 'python', '-m', 'resume_maker.cli', '--port', "$Port")
# 前台运行让终端关闭行为和 CLI 正常退出保持一致。
if ($DataDir) { $launchArgs += @('--data-dir', $DataDir) }
if ($NoBrowser) { $launchArgs += '--no-browser' }
& uv @launchArgs
exit $LASTEXITCODE
