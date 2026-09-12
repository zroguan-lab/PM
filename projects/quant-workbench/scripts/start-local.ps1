param(
    [string]$Database = 'data/live.sqlite3'
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$manifest = Join-Path $projectRoot 'run\local-runtime.json'

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw 'Project runtime is missing. Run .\scripts\setup-local.ps1 first.'
}

if (Test-Path -LiteralPath $manifest) {
    $state = Get-Content -Raw -LiteralPath $manifest | ConvertFrom-Json
    $existing = Get-Process -Id $state.supervisor_pid -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "PM-BTC is already supervised (PID $($state.supervisor_pid))."
        exit 0
    }
}

$logDirectory = Join-Path $projectRoot 'logs'
$runDirectory = Join-Path $projectRoot 'run'
New-Item -ItemType Directory -Force -Path $logDirectory, $runDirectory | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$process = Start-Process -FilePath $venvPython `
    -ArgumentList @('-m', 'pm_btc.cli', 'run-local', '--database', $Database) `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDirectory "local-supervisor-$stamp.out.log") `
    -RedirectStandardError (Join-Path $logDirectory "local-supervisor-$stamp.err.log") `
    -PassThru

Start-Sleep -Seconds 4
if ($process.HasExited) {
    throw "PM-BTC supervisor exited during startup. Check logs/local-supervisor-$stamp.err.log"
}

Write-Host "PM-BTC research stack started (supervisor PID $($process.Id))."
Write-Host 'Dashboard: http://localhost:3000/'
