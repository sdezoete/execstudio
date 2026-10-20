<#
.SYNOPSIS
  PRODUCTION: exports your organisation's server certificate from the Windows certificate
  store into certs\server.pfx for the studio, and locks the certs folder down.
  Run from an Administrator PowerShell on the server.

.DESCRIPTION
  1. Finds the certificate by thumbprint (or lists candidates if you give none).
  2. Exports it WITH its private key and full chain to certs\server.pfx, protected by a password.
  3. Saves the password in certs\pfx-password.txt.
  4. Restricts the certs folder to Administrators and SYSTEM (the account the startup task uses).
  5. Prints the lines to put in config.json.

  If the private key is marked "not exportable", ask the PKI / IT team for a .pfx file
  instead and copy it to certs\server.pfx.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\export-cert-from-store.ps1
  powershell -ExecutionPolicy Bypass -File scripts\export-cert-from-store.ps1 -Thumbprint 3A1F...
#>
#Requires -RunAsAdministrator
param(
    [string]$Thumbprint = "",
    [string]$Store = "Cert:\LocalMachine\My"
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$certs = Join-Path $root "certs"

if (-not $Thumbprint) {
    Write-Host "Certificates with a private key in $Store that are valid for server authentication:" -ForegroundColor Cyan
    Get-ChildItem $Store | Where-Object {
        $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date) -and
        ($_.EnhancedKeyUsageList.Count -eq 0 -or $_.EnhancedKeyUsageList.FriendlyName -contains "Server Authentication")
    } | Sort-Object NotAfter -Descending |
        Format-Table Thumbprint, @{n="Subject";e={$_.Subject}}, @{n="Issuer";e={$_.Issuer}}, NotAfter -AutoSize -Wrap
    Write-Host "Run again with -Thumbprint <value> for the certificate issued for this server's name."
    return
}

$cert = Get-ChildItem $Store | Where-Object { $_.Thumbprint -eq ($Thumbprint -replace "\s", "").ToUpper() }
if (-not $cert) { throw "No certificate with thumbprint $Thumbprint in $Store." }
if (-not $cert.HasPrivateKey) { throw "This certificate has no private key on this server. Ask IT for the .pfx file." }
if ($cert.Issuer -eq $cert.Subject) { Write-Warning "This certificate is self-signed. The studio refuses self-signed certificates unless tls_allow_self_signed is true." }
if ($cert.NotAfter -lt (Get-Date).AddDays(30)) { Write-Warning ("This certificate expires on {0:d}." -f $cert.NotAfter) }

$pw = Read-Host -AsSecureString "Choose a password to protect certs\server.pfx"
New-Item -ItemType Directory -Force -Path $certs | Out-Null
$pfx = Join-Path $certs "server.pfx"
try {
    Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $pw -ChainOption BuildChain -Force | Out-Null
} catch {
    throw "Export failed. The private key is probably not exportable: ask IT for a .pfx file and save it as $pfx. ($($_.Exception.Message))"
}

# Password file for the startup task (SYSTEM account), readable only by Administrators and SYSTEM.
$plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw))
Set-Content -Path (Join-Path $certs "pfx-password.txt") -Value $plain -NoNewline -Encoding ASCII
$plain = $null

& icacls $certs /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" | Out-Null

Write-Host ""
Write-Host "Exported $($cert.Subject), valid until $($cert.NotAfter.ToString('d'))." -ForegroundColor Green
Write-Host "The certs folder is now readable only by Administrators and SYSTEM."
Write-Host ""
Write-Host "Put these lines in config.json:" -ForegroundColor Cyan
Write-Host '  "tls_enabled": true,'
Write-Host '  "tls_pfx_file": "certs/server.pfx",'
Write-Host '  "tls_pfx_password_file": "certs/pfx-password.txt",'
Write-Host '  "tls_allow_self_signed": false,'
$dns = ($cert.DnsNameList | ForEach-Object { $_.Unicode }) -join ", "
if ($dns) { Write-Host ""; Write-Host "Users must open the studio using one of these names: $dns" -ForegroundColor Yellow }
