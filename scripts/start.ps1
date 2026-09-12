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
    $newer = Get-ChildItem -LiteralPath (Join-Path $repoPath 'frontend/src') -File -Recurse |
        Where-Object { $_.LastWriteTimeUtc -gt $builtAt } | Select-Object -First 1
    $needsBuild = $null -ne $newer
}
if ($needsBuild) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22 LTS first.' }
    if (-not (Test-Path -LiteralPath (Join-Path $repoPath 'frontend/node_modules'))) {
        & npm --prefix frontend ci
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    & npm --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$launchArgs = @('run', '--no-sync', 'python', '-m', 'resume_maker.cli', '--port', "$Port")
if ($DataDir) { $launchArgs += @('--data-dir', $DataDir) }
if ($NoBrowser) { $launchArgs += '--no-browser' }
& uv @launchArgs
exit $LASTEXITCODE
