# Works from any cwd: .\scripts\dev.ps1 run catalog-service
$ErrorActionPreference = 'Stop'
$commerceRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $commerceRoot
try {
    & uv run --locked --all-packages python (Join-Path $PSScriptRoot 'dev.py') @args
    $commerceExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $commerceExitCode
