# Keeps CaseMind's backend running in the background, so OCR, transcription and
# translation of the case material continue even when the desktop app is closed.
#
# The heavy work (a local model manages ~14 chars/sec) is done ahead of time, so
# the material is ready the moment you open a file.
#
#   Install:    powershell -ExecutionPolicy Bypass -File scripts\install_background_worker.ps1
#   Remove:     powershell -ExecutionPolicy Bypass -File scripts\install_background_worker.ps1 -Uninstall
#
# No admin rights needed: it registers a per-user logon task, not a service.

param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$TaskName = "CaseMind Background Worker"
$Root     = Split-Path -Parent $PSScriptRoot
$Backend  = Join-Path $Root "backend"
$Python   = Join-Path $Backend ".venv\Scripts\pythonw.exe"   # pythonw = no console window

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed '$TaskName'. Background processing will stop at next logon."
    } else {
        Write-Host "'$TaskName' is not installed."
    }
    return
}

if (-not (Test-Path $Python)) {
    throw "Backend venv not found at $Python. Run scripts\setup.ps1 first."
}

# uvicorn is started with the backend as the working directory: the database and
# data\logs paths are relative, and running from elsewhere would create a second,
# empty database.
$Action = New-ScheduledTaskAction -Execute $Python `
    -Argument "-m uvicorn app.main:app --host 127.0.0.1 --port 8000" `
    -WorkingDirectory $Backend

$Trigger = New-ScheduledTaskTrigger -AtLogOn

# Restart if it ever dies, and never let Windows stop it for running "too long" —
# translating a large chat export legitimately takes hours.
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Description "Prepares case material (OCR / transcription / Hebrew translation) in the background." `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed '$TaskName'."
Write-Host "The backend now starts at logon and keeps preparing the material with the app closed."
Write-Host "Ollama must also be running for translation - install it as a startup app if it isn't."
