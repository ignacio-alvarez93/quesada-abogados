$ErrorActionPreference = "Stop"

$TaskName = "QuesadaAbogados-ICPPlus-Scheduler"

$existing = Get-ScheduledTask `
    -TaskName $TaskName `
    -ErrorAction SilentlyContinue

if ($null -eq $existing) {
    Write-Host "ICPPLUS_AUTOSTART_NOT_INSTALLED"
    exit 0
}

Unregister-ScheduledTask `
    -TaskName $TaskName `
    -Confirm:$false

Write-Host "ICPPLUS_AUTOSTART_REMOVED = OK"
