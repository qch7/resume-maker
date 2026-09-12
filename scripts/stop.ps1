param([string]$DataDir = '')
$ErrorActionPreference = 'Stop'
if (-not $DataDir) {
    $DataDir = if ($env:RESUME_MAKER_DATA_DIR) { $env:RESUME_MAKER_DATA_DIR } else { Join-Path $env:USERPROFILE '.resume-maker' }
}
$instancePath = Join-Path $DataDir 'instance.json'
if (-not (Test-Path -LiteralPath $instancePath)) { Write-Host 'No running instance recorded.'; exit 0 }
$instance = Get-Content -LiteralPath $instancePath -Raw | ConvertFrom-Json
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $($instance.pid)"
if ($null -eq $process) { Write-Host 'Resume Maker is already stopped.'; exit 0 }
$health = Invoke-RestMethod -Uri "http://127.0.0.1:$($instance.port)/api/health" -TimeoutSec 3
if (-not $instance.instance_id -or $health.instance_id -ne $instance.instance_id) {
    throw 'The port belongs to another instance. It was not stopped.'
}
# Request normal server shutdown so active Codex children are cancelled and reaped.
$tokenPage = Invoke-WebRequest -Uri "http://127.0.0.1:$($instance.port)/" -UseBasicParsing
$match = [regex]::Match($tokenPage.Content, 'name="resume-token" content="([^"]+)"')
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$($instance.port)/api/shutdown" -Headers @{'x-resume-token'=$match.Groups[1].Value} | Out-Null
Write-Host 'Resume Maker is shutting down.'
