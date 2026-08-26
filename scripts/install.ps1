# One-time native Windows installation for opportunity-discovery.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#
# This installer is an ALTERNATIVE to the manual commands in
# docs\OPERATIONS_WINDOWS.md ("Normal install"); both produce the same
# repository-local .venv with the package installed for normal runs.
# For development (tests, linters, type checker) additionally run:
#   .\.venv\Scripts\pip install -e '.[dev]'
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# Locate a usable Python 3.11+ interpreter.
# Order: Windows py launcher (newest supported minor first), then python.exe
# on PATH. Each candidate must actually run and self-report >= 3.11, so a
# broken shim or an older interpreter on PATH is rejected rather than used.
$script:PyExe = $null
$script:PyArgs = @()

function Test-Python311 {
    param([string]$Exe, [string[]]$LauncherArgs)
    & $Exe @LauncherArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
    return ($LASTEXITCODE -eq 0)
}

if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($minor in @(14, 13, 12, 11)) {
        if (Test-Python311 -Exe "py" -Args @("-3.$minor")) {
            $script:PyExe = "py"; $script:PyArgs = @("-3.$minor"); break
        }
    }
    if (-not $script:PyExe -and (Test-Python311 -Exe "py" -Args @("-3"))) {
        $script:PyExe = "py"; $script:PyArgs = @("-3")
    }
}
if (-not $script:PyExe) {
    $pythonOnPath = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonOnPath -and (Test-Python311 -Exe $pythonOnPath.Source -Args @())) {
        $script:PyExe = $pythonOnPath.Source; $script:PyArgs = @()
    }
}
if (-not $script:PyExe) {
    throw ("No Python 3.11+ interpreter found. Tried the Windows py launcher " +
           "(py -3.11 ... -3.14) and python.exe on PATH. Install Python 3.11 or " +
           "newer from https://www.python.org/downloads/windows/ (enable 'Add " +
           "python.exe to PATH' in the installer), then re-run this script.")
}
Write-Host ("Using Python: " + (($script:PyExe + $script:PyArgs + @("(3.11+ verified)") ) -join " "))

Write-Host "Creating virtual environment..."
if (-not (Test-Path ".venv")) {
    & $script:PyExe @script:PyArgs -m venv .venv
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw ("Virtual environment creation failed: .venv\Scripts\python.exe was " +
           "not created by '" + ($script:PyExe + $script:PyArgs -join " ") +
           " -m venv .venv'. Create it manually and re-run.")
}

Write-Host "Installing package..."
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e .

Write-Host "Initializing storage and validating configuration..."
& .\.venv\Scripts\opdisc.exe init
if ($LASTEXITCODE -ne 0) { throw "opdisc init failed with exit code $LASTEXITCODE" }
& .\.venv\Scripts\opdisc.exe validate-config
if ($LASTEXITCODE -ne 0) { throw "opdisc validate-config failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "Install complete. Next steps:"
Write-Host "  .\.venv\Scripts\opdisc.exe validate-sources   # one-time live validation"
Write-Host "  .\scripts\run.ps1                             # normal run"
exit $LASTEXITCODE
