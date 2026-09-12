$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$manifest = Join-Path $projectRoot 'run\local-runtime.json'

if (-not (Test-Path -LiteralPath $manifest)) {
    Write-Host 'PM-BTC supervisor has not been started.'
    exit 0
}

$state = Get-Content -Raw -LiteralPath $manifest | ConvertFrom-Json
$process = Get-Process -Id $state.supervisor_pid -ErrorAction SilentlyContinue
if (-not $process) {
    Write-Host 'PM-BTC supervisor is not running.'
    exit 0
}

taskkill.exe /PID $state.supervisor_pid /T /F | Out-Null
Write-Host "Stopped PM-BTC supervisor tree (PID $($state.supervisor_pid))."
