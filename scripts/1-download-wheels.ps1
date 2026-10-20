<#
.SYNOPSIS
  STEP 1 - run on a laptop WITH internet access.
  Downloads the Python libraries for the Windows server into .\wheels

.DESCRIPTION
  Downloads Windows (win_amd64) wheels for Python 3.11, whatever OS the laptop runs.
  Afterwards, copy the whole exec-studio folder (including "wheels") to the server
  and run scripts\2-install-offline.ps1 there.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\1-download-wheels.ps1
  powershell -ExecutionPolicy Bypass -File scripts\1-download-wheels.ps1 -Python "C:\Python311\python.exe"
#>
param(
    [string]$Python = "py"
)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$dest = Join-Path $root "wheels"
$req  = Join-Path $root "requirements.txt"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

Write-Host "Downloading Windows / Python 3.11 wheels into $dest ..."
& $Python -m pip download -r $req --dest $dest `
    --platform win_amd64 --python-version 3.11 --implementation cp --only-binary=:all:
if ($LASTEXITCODE -ne 0) { throw "pip download failed. Check the laptop's internet access and that pip works ($Python -m pip --version)." }

Get-ChildItem $dest -Filter *.whl | Sort-Object Name | Format-Table Name, @{n="KB";e={[int]($_.Length/1KB)}} -AutoSize
Write-Host ""
Write-Host "Done. Copy the whole exec-studio folder (including 'wheels') to the server," -ForegroundColor Green
Write-Host "then run:  powershell -ExecutionPolicy Bypass -File scripts\2-install-offline.ps1" -ForegroundColor Green
