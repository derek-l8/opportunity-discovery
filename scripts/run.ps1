# Normal scheduled-run entry point for opportunity-discovery.
# The Task Scheduler task executes ONLY this script. It never modifies
# source rules, code, weights, or configuration.
$ErrorActionPreference = "Continue"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$logsDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd"
$log = Join-Path $logsDir "run-$stamp.log"

$stampIso = Get-Date -Format o
Add-Content -Path $log -Value "=== run start $stampIso ==="

& .\.venv\Scripts\opdisc.exe run --quiet *>> $log
$code = $LASTEXITCODE

$endIso = Get-Date -Format o
Add-Content -Path $log -Value "=== run end $endIso exit=$code ==="

# Retain ~14 days of logs
Get-ChildItem -Path $logsDir -Filter "run-*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } |
    Remove-Item -ErrorAction SilentlyContinue

exit $code
