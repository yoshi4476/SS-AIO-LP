# Task Scheduler registration: run this once manually in PowerShell.
#   powershell -ExecutionPolicy Bypass -File "automation\register_tasks.ps1"
# NOTE: paths are resolved from this script's own location ($PSScriptRoot),
#       so no Japanese characters appear in this file (PS5.1 encoding-safe).

$runner = Join-Path $PSScriptRoot "run_pipeline.ps1"
$retryRunner = Join-Path $PSScriptRoot "run_retry.ps1"
if (-not (Test-Path $runner)) { throw "run_pipeline.ps1 not found: $runner" }
if (-not (Test-Path $retryRunner)) { throw "run_retry.ps1 not found: $retryRunner" }

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $runner + '"')
$retryAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $retryRunner + '"')
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask -TaskName "AIO-Pipeline-Morning" -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At 08:00) -Settings $settings -Force
Register-ScheduledTask -TaskName "AIO-Pipeline-Evening" -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At 19:00) -Settings $settings -Force
Register-ScheduledTask -TaskName "AIO-Pipeline-Retry" -Action $retryAction -Trigger (New-ScheduledTaskTrigger -Daily -At 21:30) -Settings $settings -Force

Write-Host ""
Write-Host "=== registered (verify the path below is NOT garbled) ==="
(Get-ScheduledTask -TaskName "AIO-Pipeline-Evening").Actions | Format-List Execute, Arguments
Get-ScheduledTask -TaskName "AIO-Pipeline-*" | Format-Table TaskName, State
"AIO-Pipeline-Morning", "AIO-Pipeline-Evening", "AIO-Pipeline-Retry" | ForEach-Object {
    Get-ScheduledTaskInfo -TaskName $_ | Select-Object TaskName, NextRunTime
}
