param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspacePath
)

$ErrorActionPreference = "Stop"

try {
    $workspace = (Resolve-Path -LiteralPath $WorkspacePath).Path
    $metadata = Get-Content -LiteralPath (Join-Path $workspace ".opdisc\workspace.json") -Raw | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace($metadata.engine_path)) {
        throw "Workspace setup is incomplete. Run the installer with this workspace path."
    }
    $engine = $metadata.engine_path
    $opdisc = Join-Path $engine ".venv\Scripts\opdisc.exe"
    if (-not (Test-Path -LiteralPath $opdisc -PathType Leaf)) {
        throw "The dashboard is not installed. Run scripts\install.ps1 from the project folder."
    }
    Set-Location -LiteralPath $engine
    Write-Host "Opening dashboard. Close this window or press Ctrl+C to stop it."
    & $opdisc workspace-dashboard $workspace
    exit $LASTEXITCODE
}
catch {
    Write-Host ("Could not open dashboard: " + $_.Exception.Message)
    exit 1
}
