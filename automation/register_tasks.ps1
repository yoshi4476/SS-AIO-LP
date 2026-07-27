# Task Scheduler registration: run this once manually in PowerShell.
#   powershell -ExecutionPolicy Bypass -File "automation\register_tasks.ps1"
$runner = 'c:\Users\user\Desktop\システム開発\SSオウンドメディア（AIO）\automation\run_pipeline.ps1'
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $runner + '"')
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask -TaskName "AIO-Pipeline-Morning" -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At 08:00) -Settings $settings -Force
Register-ScheduledTask -TaskName "AIO-Pipeline-Evening" -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At 19:00) -Settings $settings -Force

Write-Host ""
Write-Host "=== registered ==="
Get-ScheduledTask -TaskName "AIO-Pipeline-*" | Format-Table TaskName, State
Get-ScheduledTaskInfo -TaskName "AIO-Pipeline-Morning" | Select-Object TaskName, NextRunTime
Get-ScheduledTaskInfo -TaskName "AIO-Pipeline-Evening" | Select-Object TaskName, NextRunTime
