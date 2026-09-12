$ErrorActionPreference = 'Continue'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (Test-Path -LiteralPath $venvPython) {
    Push-Location $projectRoot
    try { & $venvPython -m pm_btc.cli local-status }
    finally { Pop-Location }
}
else {
    Write-Host 'Project runtime is not installed.'
}

foreach ($endpoint in @('http://127.0.0.1:8000/api/health', 'http://127.0.0.1:3000/')) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $endpoint -TimeoutSec 10
        Write-Host "$endpoint -> HTTP $($response.StatusCode)"
    }
    catch {
        Write-Host "$endpoint -> unavailable"
    }
}
