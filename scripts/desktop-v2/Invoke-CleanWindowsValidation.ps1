[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)] [string]$InstallerPath,
  [Parameter(Mandatory = $true)] [string]$HandoffRoot,
  [Parameter(Mandatory = $true)] [string]$EvidenceDirectory,
  [switch]$RunInstaller,
  [switch]$ExternalCleanPc
)

$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem
$architecture = (Get-CimInstance Win32_OperatingSystem).OSArchitecture
$supported = $os.Caption -match 'Windows 10|Windows 11' -and $architecture -match '64'
New-Item -ItemType Directory -Path $EvidenceDirectory -Force | Out-Null
$manifest = [ordered]@{
  schemaVersion = 'desktop.clean-windows-validation.v1'
  validationClass = if ($ExternalCleanPc) { 'external-clean-pc' } else { 'local-or-ci-host' }
  operatingSystem = $os.Caption
  build = $os.BuildNumber
  architecture = $architecture
  supportedTarget = $supported
  installer = (Resolve-Path -LiteralPath $InstallerPath).Path
  installerSha256 = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash
  handoffRoot = (Resolve-Path -LiteralPath $HandoffRoot).Path
  webview2Detector = Join-Path $PSScriptRoot 'Detect-WebView2.ps1'
  installerRun = $false
  installerExitCode = $null
  smokeEvidence = $null
  repairEvidence = 'pending-external-clean-PC'
  restartEvidence = 'pending-external-clean-PC'
  uninstallEvidence = 'pending-external-clean-PC'
}
if (-not $supported) { $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'clean-pc-manifest.json'); exit 50 }
if ($RunInstaller) {
  $manifest.installerRun = $true
  $process = Start-Process -FilePath (Resolve-Path -LiteralPath $InstallerPath) -ArgumentList @('/S') -Wait -PassThru
  $manifest.installerExitCode = $process.ExitCode
  if ($process.ExitCode -notin @(0, 3010)) { $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'clean-pc-manifest.json'); exit 51 }
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'clean-pc-manifest.json')
& (Join-Path $PSScriptRoot 'Detect-WebView2.ps1') | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'webview2-detection.json')
& (Join-Path $PSScriptRoot 'Run-DesktopV2Smoke.ps1') -HandoffRoot $HandoffRoot -EvidencePath (Join-Path $EvidenceDirectory 'smoke-evidence.json')
if ($LASTEXITCODE -ne 0) { exit 52 }
exit 0
