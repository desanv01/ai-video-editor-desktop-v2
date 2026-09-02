[CmdletBinding()]
param([Parameter(Mandatory = $true)] [string]$HandoffRoot)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $HandoffRoot).Path
function Get-Sha256Hex([string]$Path) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  $stream = [System.IO.File]::OpenRead($Path)
  try { return ([System.BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
  finally { $stream.Dispose(); $sha.Dispose() }
}
if ((Split-Path $root -Leaf) -notmatch '(?i)rc6' -or $root -match '(?i)rc[45]') { throw 'Verifier accepts only a separately named RC.6 handoff.' }
foreach ($name in @('release-manifest.json','LICENSES-AND-SOURCES.md','sbom.cdx.json','SHA256SUMS.txt')) {
  if (-not (Test-Path -LiteralPath (Join-Path $root $name) -PathType Leaf)) { throw "Missing RC.6 provenance file: $name" }
}
$manifest = Get-Content -LiteralPath (Join-Path $root 'release-manifest.json') -Raw | ConvertFrom-Json
if ($manifest.product.version -ne '2.0.0-rc.6') { throw 'Release manifest is not RC.6.' }
if ($manifest.authenticode.status -ne 'not-claimed') { throw 'RC.6 must not claim Authenticode without external evidence.' }
if ($manifest.trustRoot.privateSeedIncluded -ne $false) { throw 'Private signing seed must not be included.' }
$ffmpeg = @($manifest.components | Where-Object componentId -eq 'ffmpeg')
if ($ffmpeg.Count -ne 1 -or $ffmpeg[0].version -ne '8.1.1') { throw 'Exactly one FFmpeg 8.1.1 component is required.' }
$forbidden = @(Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object Name -Match '(?i)(ed25519-seed|private-key|\.pfx$|\.p12$|\.pem$|\.key$)')
if ($forbidden.Count -gt 0) { throw 'Private key material is present in the handoff.' }
foreach ($line in Get-Content -LiteralPath (Join-Path $root 'SHA256SUMS.txt')) {
  if ($line -notmatch '^([0-9a-f]{64})  (.+)$') { throw "Invalid checksum line: $line" }
  $path = Join-Path $root $Matches[2]
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Checksummed file is missing: $($Matches[2])" }
  if ((Get-Sha256Hex $path) -ne $Matches[1]) { throw "Checksum mismatch: $($Matches[2])" }
}
Write-Output '{"status":"verified","version":"2.0.0-rc.6","authenticode":"not-claimed"}'
