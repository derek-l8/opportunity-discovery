param(
    [string]$VenvPath = ".venv",
    [string]$WorkspacePath = "",
    [switch]$SkipWorkspaceSetup,
    [switch]$ProbeOnly
)

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

# Python 3.14 is recommended for new installations. Python 3.11-3.14 remain
# supported. Locate the newest compatible installed interpreter via the
# Windows launcher, then try python.exe on PATH.
$script:PyExe = $null
$script:PyArgs = @()
$attemptedRoutes = @("py -3.14", "py -3.13", "py -3.12", "py -3.11", "python.exe on PATH")

function Test-Python311 {
    param([string]$Exe, [string[]]$LauncherArgs)

    # Probes are intentionally non-fatal: a missing launcher version is an
    # expected condition even though the rest of this installer fails fast.
    try {
        & $Exe @LauncherArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($minor in @(14, 13, 12, 11)) {
        if (Test-Python311 -Exe "py" -LauncherArgs @("-3.$minor")) {
            $script:PyExe = "py"; $script:PyArgs = @("-3.$minor"); break
        }
    }
}
if (-not $script:PyExe) {
    $pythonOnPath = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonOnPath -and (Test-Python311 -Exe $pythonOnPath.Source -LauncherArgs @())) {
        $script:PyExe = $pythonOnPath.Source; $script:PyArgs = @()
    }
}
if (-not $script:PyExe) {
    throw ("No compatible Python interpreter found. Tried: " +
           ($attemptedRoutes -join ", ") + ". Install Python 3.11, 3.12, 3.13, " +
           "or 3.14, then re-run this script.")
}
Write-Host ("Using Python: " + ((@($script:PyExe) + $script:PyArgs + @("(compatible version verified)")) -join " "))
if ($ProbeOnly) { exit 0 }

Write-Host "Creating virtual environment..."
if (-not (Test-Path $VenvPath)) {
    & $script:PyExe @script:PyArgs -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed with exit code $LASTEXITCODE" }
}
if (-not (Test-Path (Join-Path $VenvPath "Scripts\python.exe"))) {
    throw ("Virtual environment creation failed: Scripts\python.exe was " +
           "not created by '" + ($script:PyExe + $script:PyArgs -join " ") +
           " -m venv " + $VenvPath + "'. Create it manually and re-run.")
}

Write-Host "Installing package..."
$venvPython = Join-Path $VenvPath "Scripts\python.exe"
$venvOpdisc = Join-Path $VenvPath "Scripts\opdisc.exe"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed with exit code $LASTEXITCODE" }
& $venvPython -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "Package installation failed with exit code $LASTEXITCODE" }

Write-Host "Initializing storage and validating configuration..."
& $venvOpdisc init
if ($LASTEXITCODE -ne 0) { throw "opdisc init failed with exit code $LASTEXITCODE" }
& $venvOpdisc validate-config
if ($LASTEXITCODE -ne 0) { throw "opdisc validate-config failed with exit code $LASTEXITCODE" }

if (-not $SkipWorkspaceSetup) {
    $documents = [Environment]::GetFolderPath("MyDocuments")
    $defaultWorkspace = Join-Path $documents "Opportunity-Workspace"
    if ([string]::IsNullOrWhiteSpace($WorkspacePath)) {
        $answer = Read-Host "Private workspace location [$defaultWorkspace]"
        $WorkspacePath = if ([string]::IsNullOrWhiteSpace($answer)) { $defaultWorkspace } else { $answer }
    }
    Write-Host "Initializing private workspace..."
    & $venvOpdisc init-workspace $WorkspacePath --engine-path $repoRoot
    if ($LASTEXITCODE -ne 0) { throw "opdisc init-workspace failed with exit code $LASTEXITCODE" }
}

Write-Host ""
Write-Host "Install complete. Next steps:"
Write-Host "  .\.venv\Scripts\opdisc.exe validate-sources   # one-time live validation"
Write-Host "  .\scripts\run.ps1                             # normal run"
if (-not $SkipWorkspaceSetup) {
    Write-Host "  Private workspace: $WorkspacePath"
}
exit $LASTEXITCODE
