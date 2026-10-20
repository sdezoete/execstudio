<#
.SYNOPSIS
  Runs the studio automatically when the server starts, and opens its port in Windows Firewall.
  Run from an Administrator PowerShell.

.DESCRIPTION
  Registers a Windows Scheduled Task "ExecutivePresentationStudio" that starts
  scripts\run-server.bat at boot under the SYSTEM account and restarts it if it stops.
  Uses only built-in Windows features (no extra service wrapper to install).

  The port (and the optional HTTP-to-HTTPS redirect port) are read from config.json.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install-startup-task.ps1
  powershell -ExecutionPolicy Bypass -File scripts\install-startup-task.ps1 -Remove
#>
#Requires -RunAsAdministrator
param(
    [switch]$Remove
)
$ErrorActionPreference = "Stop"
$name = "ExecutivePresentationStudio"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$cfgPath = Join-Path $root "config.json"
if (Test-Path $cfgPath) {
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
} elseif ($Remove) {
    $cfg = [pscustomobject]@{}
} else {
    throw "config.json not found. Run scripts\2-install-offline.ps1 first."
}
$Port = if ($cfg.port) { [int]$cfg.port } else { 8080 }
$https = [bool]$cfg.tls_enabled
$redirect = if ($https -and $cfg.http_redirect_port) { [int]$cfg.http_redirect_port } else { 0 }
if (-not $https -and -not $Remove) {
    Write-Warning "config.json has tls_enabled = false: the studio would serve plain HTTP. Set up HTTPS first (README: HTTPS)."
    $answer = Read-Host "Continue anyway? (y/N)"
    if ($answer -ne "y") { return }
}

Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
}
if ($Remove) {
    Write-Host "Removed the startup task and firewall rule." -ForegroundColor Green
    return
}

New-Item -ItemType Directory -Force -Path (Join-Path $root "logs") | Out-Null
$bat = Join-Path $root "scripts\run-server.bat"
$console = Join-Path $root "logs\console.log"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"`"$bat`" >> `"$console`" 2>&1`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Executive Presentation Studio web server ($root)" | Out-Null

$ports = @($Port) + @($redirect | Where-Object { $_ -gt 0 })
New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $ports -Action Allow `
    -Profile Domain, Private | Out-Null

Start-ScheduledTask -TaskName $name
Start-Sleep -Seconds 4
$ok = (Test-NetConnection -ComputerName localhost -Port $Port -WarningAction SilentlyContinue).TcpTestSucceeded
if ($ok) {
    Write-Host "Running on port $Port. Firewall open for: $($ports -join ', ')." -ForegroundColor Green
} else {
    Write-Warning "The task started but nothing is listening on port $Port yet. Check logs\server.log (for example a certificate problem)."
}
$scheme = if ($https) { "https" } else { "http" }
Write-Host "Users open: ${scheme}://<the server name on the certificate>:$Port"
