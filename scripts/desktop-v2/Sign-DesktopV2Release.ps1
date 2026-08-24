[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)] [string]$ArtifactRoot,
  [string]$CertificateThumbprint = $env:AIVE_SIGNING_CERT_THUMBPRINT,
  [string]$TimestampUrl = $env:AIVE_TIMESTAMP_URL,
  [switch]$RequireSigning,
  [switch]$VerifyOnly,
  [string]$SignToolPath = 'signtool.exe'
)

$ErrorActionPreference = 'Stop'
$required = $RequireSigning -or $env:AIVE_REQUIRE_AUTHENTICODE -eq '1'
$root = (Resolve-Path -LiteralPath $ArtifactRoot).Path
$peFiles = @(Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object { $_.Extension -in @('.exe', '.dll', '.msi') } | Sort-Object FullName)
if ($peFiles.Count -eq 0) {
  if ($required) { Write-Error 'No PE files were found for required Authenticode signing.'; exit 30 }
  Write-Output '{"status":"pending","reason":"no PE files"}'
  exit 0
}

if (-not $VerifyOnly -and $required) {
  if (-not $CertificateThumbprint -or $CertificateThumbprint -notmatch '^[0-9A-Fa-f]{40}$') {
    Write-Error 'Required signing needs an externally supplied OV/EV certificate thumbprint in the current user or machine certificate store.'
    exit 31
  }
  if (-not $TimestampUrl -or $TimestampUrl -notmatch '^https://') {
    Write-Error 'Required signing needs an RFC3161 HTTPS timestamp URL.'
    exit 31
  }
  foreach ($file in $peFiles) {
    & $SignToolPath sign /sha1 $CertificateThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $file.FullName
    if ($LASTEXITCODE -ne 0) { Write-Error "signtool failed for $($file.Name) with exit code $LASTEXITCODE"; exit 32 }
  }
}

$results = foreach ($file in $peFiles) {
  $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
  [ordered]@{
    path = $file.FullName.Substring($root.Length).TrimStart('\','/')
    status = [string]$signature.Status
    signer = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
    thumbprint = if ($signature.SignerCertificate) { $signature.SignerCertificate.Thumbprint } else { $null }
  }
}
$unsigned = @($results | Where-Object { $_.status -ne 'Valid' })
$results | ConvertTo-Json -Depth 4
if ($required -and $unsigned.Count -gt 0) {
  Write-Error "Release signing verification failed for $($unsigned.Count) PE file(s)."
  exit 33
}
if (-not $required -and $unsigned.Count -gt 0) {
  Write-Warning "Authenticode signing is pending for $($unsigned.Count) PE file(s); no signed evidence is claimed."
}
exit 0
