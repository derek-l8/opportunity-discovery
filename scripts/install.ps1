# One-time native Windows installation for opportunity-discovery.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install.ps1
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# Locate Python 3.11+
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    python --version 2>$null | Out-Null
}

Write-Host "Creating virtual environment..."
if (-not (Test-Path ".venv")) {
    py -3.12 -m venv .venv 2>$null
    if (-not (Test-Path ".venv")) { py -3.11 -m venv .venv }
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "No .venv with python.exe found; install Python 3.11+ from python.org"
}

Write-Host "Installing package..."
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -e .

Write-Host "Initializing storage and validating configuration..."
& .\.venv\Scripts\opdisc.exe init
& .\.venv\Scripts\opdisc.exe validate-config

Write-Host ""
Write-Host "Install complete. Next steps:"
Write-Host "  .\.venv\Scripts\opdisc.exe validate-sources   # one-time live validation"
Write-Host "  .\scripts\run.ps1                             # normal run"
exit $LASTEXITCODE
