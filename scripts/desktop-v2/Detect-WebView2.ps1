[CmdletBinding()]
param(
  [ValidateSet('EvergreenBootstrapper','StandaloneInstaller','FixedRuntime')]
  [string]$ArtifactKind,
  [string]$ArtifactPath,
  [string]$ExpectedSha256,
  [switch]$Install,
  [switch]$Offline,
  [string]$FixedRuntimeRoot
)

$ErrorActionPreference = 'Stop'
$clientGuid = '{F3017226-FE2A-4A67-A3F6-CFC0C4E1D5A1}'
$policy = 'detect-before-launch; Evergreen bootstrapper online or Standalone Installer offline; no-silent-download'

function Write-Status([bool]$available, [string]$source, [string]$version, [string]$detail, [int]$exitCode) {
  $payload = [ordered]@{
    schemaVersion = 'desktop.webview2-runtime.v1'
    available = $available
    version = if ($version) { $version } else { $null }
    source = $source
    installPolicy = $policy
    detail = $detail
    remediationCodes = if ($available) { @() } else { @('WEBVIEW2_RUNTIME_REQUIRED') }
  }
  $payload | ConvertTo-Json -Compress
  exit $exitCode
}

function Get-RegistryVersion([Microsoft.Win32.RegistryHive]$hive, [Microsoft.Win32.RegistryView]$view) {
  $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, $view)
  try {
    $key = $base.OpenSubKey("SOFTWARE\Microsoft\EdgeUpdate\Clients\$clientGuid")
    try { if ($key) { return [string]$key.GetValue('pv', '') } } finally { if ($key) { $key.Dispose() } }
  } finally { $base.Dispose() }
  return ''
}

function Get-VerifiedExecutableVersion([string]$path) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return '' }
  try {
    $item = Get-Item -LiteralPath $path -Force
    if ($item.Length -lt 1MB -or $item.Length -gt 1GB) { return '' }
    $version = ([string]$item.VersionInfo.ProductVersion).Trim()
    if ($version -notmatch '^\d+\.\d+\.\d+\.\d+$') {
      $version = ([string]$item.VersionInfo.FileVersion).Trim()
    }
    if ($version -match '^\d+\.\d+\.\d+\.\d+$') { return $version }
  } catch {
    return ''
  }
  return ''
}

function Get-FilesystemRuntime {
  $roots = @(
    [Environment]::GetEnvironmentVariable('ProgramFiles(x86)'),
    [Environment]::GetEnvironmentVariable('ProgramFiles'),
    [Environment]::GetEnvironmentVariable('LOCALAPPDATA')
  ) | Where-Object { $_ }
  foreach ($root in $roots) {
    $applicationRoot = Join-Path (Join-Path (Join-Path $root 'Microsoft') 'EdgeWebView') 'Application'
    if (-not (Test-Path -LiteralPath $applicationRoot -PathType Container)) { continue }
    $directories = @()
    $seen = 0
    foreach ($directory in (Get-ChildItem -LiteralPath $applicationRoot -Directory -Force -ErrorAction SilentlyContinue)) {
      if ($seen -ge 64) { break }
      $seen++
      if ($directory.Name -match '^\d+\.\d+\.\d+\.\d+$') { $directories += $directory }
    }
    foreach ($directory in ($directories | Sort-Object { [version]$_.Name } -Descending)) {
      $exe = Join-Path $directory.FullName 'msedgewebview2.exe'
      $version = Get-VerifiedExecutableVersion $exe
      if ($version -and $version -eq $directory.Name) {
        return @{ available = $true; source = 'evergreen-filesystem'; version = $version }
      }
    }
  }
  return @{ available = $false; source = 'not-detected'; version = '' }
}

function Get-DetectedRuntime {
  if ($env:WEBVIEW2_BROWSER_EXECUTABLE_FOLDER) {
    $fixedExe = Join-Path $env:WEBVIEW2_BROWSER_EXECUTABLE_FOLDER 'msedgewebview2.exe'
    $fixedVersion = Get-VerifiedExecutableVersion $fixedExe
    if ($fixedVersion) {
      return @{ available = $true; source = 'fixed-runtime'; version = $fixedVersion }
    }
  }
  foreach ($candidate in @(
    @{ hive = [Microsoft.Win32.RegistryHive]::CurrentUser; view = [Microsoft.Win32.RegistryView]::Registry64; source = 'evergreen-user' },
    @{ hive = [Microsoft.Win32.RegistryHive]::CurrentUser; view = [Microsoft.Win32.RegistryView]::Registry32; source = 'evergreen-user' },
    @{ hive = [Microsoft.Win32.RegistryHive]::LocalMachine; view = [Microsoft.Win32.RegistryView]::Registry64; source = 'evergreen-machine' },
    @{ hive = [Microsoft.Win32.RegistryHive]::LocalMachine; view = [Microsoft.Win32.RegistryView]::Registry32; source = 'evergreen-machine' }
  )) {
    $version = Get-RegistryVersion $candidate.hive $candidate.view
    if ($version) { return @{ available = $true; source = $candidate.source; version = $version } }
  }
  return Get-FilesystemRuntime
}

if (-not $Install) {
  $detected = Get-DetectedRuntime
  if ($detected.available) {
    Write-Status $true $detected.source $detected.version 'WebView2 detected before shell launch.' 0
  }
  Write-Status $false 'not-detected' '' 'WebView2 is required. Use the official Evergreen bootstrapper online or Standalone Installer offline; this script never downloads a runtime implicitly.' 20
}

if (-not $ArtifactPath -or -not (Test-Path -LiteralPath $ArtifactPath -PathType Leaf)) {
  Write-Status $false 'install-input-missing' '' 'An externally supplied WebView2 artifact is required for an explicit install.' 24
}
if (-not $ExpectedSha256 -or $ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
  Write-Status $false 'provenance-missing' '' 'Release installation requires an externally supplied SHA-256 provenance record.' 24
}
$actual = (Get-FileHash -LiteralPath $ArtifactPath -Algorithm SHA256).Hash
if ($actual -ne $ExpectedSha256.ToUpperInvariant()) {
  Write-Status $false 'checksum-mismatch' '' 'The supplied WebView2 artifact does not match its recorded SHA-256.' 21
}
if ($Offline -and $ArtifactKind -eq 'EvergreenBootstrapper') {
  Write-Status $false 'offline-bootstrapper-rejected' '' 'The Evergreen bootstrapper is online-only. Use the Microsoft Standalone Installer for offline installation.' 23
}

if ($ArtifactKind -eq 'FixedRuntime') {
  if (-not $FixedRuntimeRoot -or -not (Test-Path -LiteralPath (Join-Path $FixedRuntimeRoot 'msedgewebview2.exe') -PathType Leaf)) {
    Write-Status $false 'fixed-runtime-invalid' '' 'A fixed runtime requires a verified folder containing msedgewebview2.exe.' 21
  }
  Write-Status $true 'fixed-runtime' $FixedRuntimeRoot 'Fixed runtime provenance and executable path were checked; the application must apply its documented ACL policy.' 0
}

$process = Start-Process -FilePath (Resolve-Path -LiteralPath $ArtifactPath) -ArgumentList @('/silent','/install') -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -notin @(0, 3010)) {
  Write-Status $false 'installer-failed' '' "WebView2 installer exited with code $($process.ExitCode)." 22
}
$detected = Get-DetectedRuntime
if ($detected.available) {
  Write-Status $true $detected.source $detected.version "WebView2 installation completed with exit code $($process.ExitCode)." 0
}
Write-Status $false 'install-not-detected' '' 'The installer returned success but the runtime was not detected afterward.' 22
