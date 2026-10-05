# Registers a daily 10:00 scheduled task "SLOEvents" that runs `python run.py` in the repo dir.
# Output is appended to data\run.log.
# Uninstall: Unregister-ScheduledTask -TaskName "SLOEvents" -Confirm:$false
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
New-Item -ItemType Directory -Force -Path (Join-Path $repo "data") | Out-Null

$cmd = "`"$python`" run.py >> data\run.log 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $cmd" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At 10:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "SLOEvents" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Scrape SLO County events and publish the page" -Force | Out-Null
Write-Host "Registered SLOEvents: daily 10:00, $python run.py in $repo"
