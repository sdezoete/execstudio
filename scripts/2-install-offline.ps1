<#
.SYNOPSIS
  STEP 2 - run on the air-gapped Windows server.
  Creates .venv and installs the libraries from .\wheels without internet access.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\2-install-offline.ps1
  powershell -ExecutionPolicy Bypass -File scripts\2-install-offline.ps1 -Python "D:\Python311\python.exe"
#>
param(
    [string]$Python = ""
)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

# 1. Find Python 3.11
if (-not $Python) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $Python = (& py -3.11 -c "import sys; print(sys.executable)" 2>$null)
    }
    if (-not $Python) {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd) { $Python = $cmd.Source }
    }
}
if (-not $Python) { throw "Python 3.11 was not found. Pass its path: -Python 'C:\Path\To\python.exe'" }
$ver = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Host "Using Python $ver at $Python"
if ($ver -ne "3.11") { Write-Warning "The wheels were downloaded for Python 3.11; this is $ver. Re-run step 1 with a matching version if installation fails." }

# 2. Virtual environment
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv ..."
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
}
$venvPy = Join-Path $root ".venv\Scripts\python.exe"

# 3. Libraries from the local wheels folder (no internet)
if (Test-Path "wheels") {
    Write-Host "Installing libraries from .\wheels ..."
    & $venvPy -m pip install --no-index --find-links wheels -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Offline install failed. Make sure step 1 was run and the 'wheels' folder was copied." }
} else {
    Write-Warning "No 'wheels' folder found. The studio will run with the built-in PowerPoint writer and without PDF reading."
}

# 4. Settings and folders
if (-not (Test-Path "config.json")) {
    Copy-Item "config.example.json" "config.json"
    Write-Host "Created config.json - set llm_base_url and llm_model for your DeepSeek server." -ForegroundColor Yellow
}
New-Item -ItemType Directory -Force -Path "logs", "work", "data\templates", "certs" | Out-Null

# 5. Check
& $venvPy -c "import sys; sys.path.insert(0, '.'); from studio import slides, tls; from studio.extract import PDF_SUPPORTED; print('PowerPoint engine:', slides.ENGINE, '| PDF reading:', PDF_SUPPORTED, '| .pfx certificates:', tls.HAVE_CRYPTOGRAPHY)"
Write-Host ""
Write-Host "Installed. Next: set up HTTPS with your certificate (Administrator PowerShell):" -ForegroundColor Green
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\export-cert-from-store.ps1" -ForegroundColor Green
Write-Host "Then start the studio with:  scripts\run-server.bat" -ForegroundColor Green
Write-Host "Run it at startup (as Administrator): powershell -ExecutionPolicy Bypass -File scripts\install-startup-task.ps1" -ForegroundColor Green
