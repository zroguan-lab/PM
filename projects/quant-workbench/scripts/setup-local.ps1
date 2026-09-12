param(
    [switch]$WithMl
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$bootstrapPython = 'C:\Users\Lenovo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    if (-not (Test-Path -LiteralPath $bootstrapPython)) {
        throw 'Python 3.11+ was not found. Install Python, then rerun this script.'
    }
    & $bootstrapPython -m venv (Join-Path $projectRoot '.venv')
}

Push-Location $projectRoot
try {
    $package = if ($WithMl) { '.[ml]' } else { '.' }
    & $venvPython -m pip install -e $package
    Push-Location (Join-Path $projectRoot 'web')
    try {
        npm install
        npm run build
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}

Write-Host 'Local runtime is ready. Start it with .\scripts\start-local.ps1'
