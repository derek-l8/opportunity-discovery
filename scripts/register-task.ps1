# Registers a Windows Task Scheduler task that runs scripts\run.ps1 daily.
# REVIEW BEFORE RUNNING. This script is never invoked automatically.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1
$ErrorActionPreference = "Stop"

$taskName = "OpportunityDiscovery"
$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $repoRoot "scripts\run.ps1"

if (-not (Test-Path $scriptPath)) { throw "missing $scriptPath" }

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`"" `
    -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At 07:30
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $taskName `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "opportunity-discovery deterministic collection run (public lead layer)"

Write-Host "Task '$taskName' registered (daily 07:30)."
Write-Host "Remove or disable with scripts\unregister-task.ps1."
