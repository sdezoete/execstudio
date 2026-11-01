<#
.SYNOPSIS
  Run on the laptop. Builds .\usb_migration\exec-studio: the release to copy to the air-gapped server.

.DESCRIPTION
  Takes the files tracked in git (minus dev-only files), the wheels, and a server .env made
  from .env.example (DEVELOPMENT=False, no OpenAI key, LLM_API_KEY empty). Writes VERSION.txt
  with the git version, so the server always shows which release it runs.
  For a release, commit and tag first (git tag v1.5.2), then run this script.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\make-usb.ps1
#>
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root
$out  = Join-Path $root "usb_migration"
$dest = Join-Path $out "exec-studio"

$version = (git describe --tags --always --dirty)
if (git status --porcelain) { Write-Warning "Uncommitted changes are included: this is not a clean release ($version)." }
if (-not (Get-ChildItem "wheels" -Filter *.whl -ErrorAction SilentlyContinue)) { throw "No wheels in .\wheels. Run scripts\1-download-wheels.ps1 first." }

if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force -Path $dest | Out-Null

# 1. Files tracked in git, without the dev-only ones
$skip = '^(\.vscode/|\.gitattributes$|\.gitignore$|improvements_)'
foreach ($f in (git -c core.quotepath=off ls-files)) {
    if ($f -match $skip) { continue }
    $target = Join-Path $dest $f
    New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
    Copy-Item -LiteralPath $f -Destination $target
}

# 2. Wheels (not in git)
New-Item -ItemType Directory -Force -Path (Join-Path $dest "wheels") | Out-Null
Copy-Item "wheels\*.whl" (Join-Path $dest "wheels")

# 3. Server .env: from .env.example, never from the laptop's own .env (that holds the OpenAI key)
$inDev = $false
$envLines = foreach ($line in Get-Content ".env.example") {
    if ($line -match '^# --- Development only') { $inDev = $true; continue }
    if ($line -match '^# --- Production only') { $inDev = $false }
    if (-not $inDev) { $line -replace '^DEVELOPMENT=.*', 'DEVELOPMENT=False' }
}
[IO.File]::WriteAllLines((Join-Path $dest ".env"), $envLines, (New-Object Text.UTF8Encoding $false))

# 4. Version stamp
[IO.File]::WriteAllLines((Join-Path $dest "VERSION.txt"), @("exec-studio $version", "built $(Get-Date -Format s)"))

$textFiles = Get-ChildItem $dest -Recurse -File -Force | Where-Object { $_.Extension -notin ".whl", ".pptx", ".xlsx", ".pdf", ".png", ".svg" }
if (@($textFiles | Select-String -Pattern 'sk-[A-Za-z0-9_-]{8}').Count -gt 0) { throw "An OpenAI key ended up in the package. Do not copy it." }

Write-Host ""
Write-Host "Built $dest ($version)." -ForegroundColor Green
Write-Host "Copy the 'exec-studio' folder in usb_migration to the USB stick, plus python-3.11.x-amd64.exe for a first install." -ForegroundColor Green
