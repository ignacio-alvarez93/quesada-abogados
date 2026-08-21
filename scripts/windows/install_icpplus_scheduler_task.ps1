$ErrorActionPreference = "Stop"

$TaskName = "QuesadaAbogados-ICPPlus-Scheduler"

$ProjectRoot = (
    Resolve-Path (
        Join-Path $PSScriptRoot "..\.."
    )
).Path

$Launcher = Join-Path `
    $ProjectRoot `
    "scripts\windows\start_icpplus_scheduler_worker.cmd"

if (-not (Test-Path $Launcher)) {
    throw "Launcher ICP Plus no encontrado: $Launcher"
}

$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$Launcher`"" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger `
    -AtLogOn `
    -User $env:USERNAME

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

$Task = New-ScheduledTask `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal

Register-ScheduledTask `
    -TaskName $TaskName `
    -InputObject $Task `
    -Force | Out-Null

Write-Host "ICPPLUS_AUTOSTART_INSTALLED = OK"
Write-Host "TASK_NAME = $TaskName"
Write-Host "USER      = $env:USERNAME"
Write-Host "PROJECT   = $ProjectRoot"
Write-Host "LAUNCHER  = $Launcher"
