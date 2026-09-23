# Reconfigures the "run TDI main" scheduled task. Run from an ADMIN PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_scheduled_task.ps1
#
# - runs run_bot.cmd (project venv, UTF-8, logs to logs\top_deals.log)
# - no 3-day execution limit
# - restarts up to 5 times, 5 minutes apart, if the bot crashes
# - keeps running on battery
# - starts at logon, plus a daily 08:00 check that starts it if it is not running

$ErrorActionPreference = "Stop"

$dir = Split-Path -Parent $PSScriptRoot
$taskName = "run TDI main"

$action = New-ScheduledTaskAction -Execute (Join-Path $dir "run_bot.cmd") -WorkingDirectory $dir
$triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"),
    (New-ScheduledTaskTrigger -Daily -At 8:00am)
)
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

$running = (Get-ScheduledTask -TaskName $taskName).State -eq "Running"
if ($running) { Stop-ScheduledTask -TaskName $taskName }

Set-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings | Out-Null
Start-ScheduledTask -TaskName $taskName

$task = Get-ScheduledTask -TaskName $taskName
Write-Host "Task updated. State: $($task.State)"
Write-Host "Action: $($task.Actions[0].Execute)"
Write-Host "Restart count: $($task.Settings.RestartCount), time limit: $($task.Settings.ExecutionTimeLimit)"
