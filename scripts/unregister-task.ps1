# Removes (or disables) the Windows Task Scheduler task created by
# register-task.ps1. Review before running.
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\unregister-task.ps1          # remove
#   powershell -ExecutionPolicy Bypass -File scripts\unregister-task.ps1 -Disable # disable only
param(
    [switch]$Disable
)
$ErrorActionPreference = "Stop"
$taskName = "OpportunityDiscovery"

if ($Disable) {
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    Write-Host "Task '$taskName' disabled."
} else {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Task '$taskName' removed."
}
