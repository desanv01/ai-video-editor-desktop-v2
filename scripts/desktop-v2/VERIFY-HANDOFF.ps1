[CmdletBinding()]
param(
  [string]$Root = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path

function Relative-Name([string]$Path) {
  return ((Resolve-Path -LiteralPath $Path).Path.Substring($rootPath.Length).TrimStart('\','/') -replace '\\','/')
}

$actual = @(Get-ChildItem -LiteralPath $rootPath -Recurse -File | ForEach-Object { Relative-Name $_.FullName }) | Sort-Object
$required = @(
  'AI Video Editor Desktop V2 Setup.exe',
  'Catalog/offline-catalog.json',
  'Catalog/offline-catalog.sig',
  'Catalog/lecturer-release-public-key.json',
  'Components/aive-engine-manifest.json',
  'Components/aive-engine-manifest.sig',
  'Components/ffmpeg-manifest.json',
  'Components/ffmpeg-manifest.sig',
  'SHA256SUMS.txt',
  'VERIFY-HANDOFF.ps1',
  'verify-handoff-signatures.py',
  'release-manifest.json'
) | Sort-Object
$missing = @($required | Where-Object { $_ -notin $actual })
if ($missing) { throw "Missing critical handoff files: $($missing -join ', ')" }

$manifest = Get-Content -LiteralPath (Join-Path $rootPath 'release-manifest.json') -Raw | ConvertFrom-Json
if ($manifest.product.identifier -ne 'com.fyp.ai-video-editor.desktop-v2') { throw 'Unexpected Desktop V2 product identifier.' }
if ($manifest.product.version -notmatch '^2\.0\.0-rc\.[3-9][0-9]*$') { throw "Expected rc.3 or higher handoff, found $($manifest.product.version)." }
if ($manifest.installer.target -ne 'C:/Program Files/AI Video Editor Desktop V2') { throw 'Canonical installer target is incorrect.' }

$sumPath = Join-Path $rootPath 'SHA256SUMS.txt'
$sumEntries = @{}
foreach ($line in Get-Content -LiteralPath $sumPath) {
  if ([string]::IsNullOrWhiteSpace($line)) { continue }
  if ($line -notmatch '^([0-9a-fA-F]{64})  (.+)$') { throw "Invalid checksum line: $line" }
  $relative = $matches[2] -replace '\\','/'
  if ($sumEntries.ContainsKey($relative)) { throw "Duplicate checksum entry: $relative" }
  $sumEntries[$relative] = $matches[1].ToLowerInvariant()
}
$expectedChecksums = @($actual | Where-Object { $_ -ne 'SHA256SUMS.txt' }) | Sort-Object
$sumNames = @($sumEntries.Keys) | Sort-Object
if (@(Compare-Object $expectedChecksums $sumNames).Count -ne 0) { throw 'SHA256SUMS.txt does not cover exactly every file except itself.' }
foreach ($relative in $expectedChecksums) {
  $path = Join-Path $rootPath ($relative -replace '/', '\')
  $actualHash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actualHash -ne $sumEntries[$relative]) { throw "Checksum mismatch: $relative" }
}

foreach ($file in Get-ChildItem -LiteralPath $rootPath -Recurse -File) {
  if ($file.Name -match '(?i)(ed25519-seed|private-key|\.pem$|\.pfx$|\.p12$|\.key$)') { throw "Private key material is present: $($file.FullName)" }
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw 'Signature verification requires Python with cryptography; no installer or component was executed.' }
& $python.Source (Join-Path $rootPath 'verify-handoff-signatures.py') $rootPath
if ($LASTEXITCODE -ne 0) { throw 'Ed25519 signature verification failed.' }
Write-Output "Handoff verification PASS: $rootPath"
