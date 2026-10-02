[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Installer, [Parameter(Mandatory=$true)][string]$EvidenceDir)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$evidenceRoot = (Resolve-Path -LiteralPath $EvidenceDir).Path
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'Actual installer lifecycle requires an elevated disposable Windows runner.'
}

function Assert-True($Condition, [string]$Message) {
  $values = @($Condition)
  if ($values.Count -ne 1 -or $values[0] -isnot [bool]) {
    throw "$Message Assertion returned $($values.Count) values instead of one Boolean: $($values -join ', ')."
  }
  if (-not $values[0]) { throw $Message }
}
function Invoke-Bounded([string]$Path, [string]$Arguments, [string]$Stage,
                        [string]$WorkingDirectory = (Split-Path -Parent $Path),
                        [string]$ExitEvidencePath = '') {
  $process = Start-Process -FilePath $Path -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru
  if (-not $process.WaitForExit(180000)) {
    $process.Kill()
    if ($ExitEvidencePath) {
      [pscustomobject]@{ status='timed-out'; stage=$Stage; timeoutSeconds=180 } |
        ConvertTo-Json | Set-Content -LiteralPath $ExitEvidencePath
    }
    throw "$Stage timed out after 180 seconds."
  }
  $process.Refresh()
  if ($ExitEvidencePath) {
    [pscustomobject]@{ status='completed'; stage=$Stage; exitCode=$process.ExitCode } |
      ConvertTo-Json | Set-Content -LiteralPath $ExitEvidencePath
  }
  if ($process.ExitCode -ne 0) { throw "$Stage exited $($process.ExitCode)." }
  return $process.ExitCode
}

$registry = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
  [Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
$rollbackPath = 'Software\AI Video Editor Desktop V2 RC6 Installer Rollback'
$productPath = 'Software\AI Video Editor Desktop V2'
$arpPath = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor Desktop V2'
$parent = Join-Path $env:ProgramFiles 'AI Video Editor Desktop V2'
$parentPrefix = $parent.TrimEnd('\') + '\'
Assert-True (-not ($evidenceRoot.Equals($parent, [StringComparison]::OrdinalIgnoreCase) -or
  $evidenceRoot.StartsWith($parentPrefix, [StringComparison]::OrdinalIgnoreCase))) 'Evidence directory must be outside the product tree.'
$shell = Join-Path $parent 'Shell'
$stage = Join-Path $parent 'Shell.rc6-staging'
$backup = Join-Path $parent 'Shell.rc6-rollback'
$machineInstaller = Join-Path $env:ProgramData 'AI Video Editor\Installer'
$sentinel = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'AI Video Editor\Projects\rc8-ci-preserve.txt'

try {
  Assert-True (-not (Test-Path -LiteralPath $shell)) 'Runner has an existing product installation.'
  Assert-True (-not (Test-Path -LiteralPath $stage)) 'Runner has an existing staging directory.'
  Assert-True (-not (Test-Path -LiteralPath $backup)) 'Runner has an existing backup directory.'
  Assert-True ($null -eq $registry.OpenSubKey($rollbackPath)) 'Runner has an existing rollback record.'

  # Exercise the production journal's genuine registry-write failure path.
  # Hold a full-control handle so the temporary denial can always be removed.
  $deniedKey = $registry.CreateSubKey($rollbackPath)
  $deny = [Security.AccessControl.RegistryAccessRule]::new(
    $identity.User,
    [Security.AccessControl.RegistryRights]('SetValue, Delete, CreateSubKey'),
    [Security.AccessControl.AccessControlType]::Deny)
  $acl = $deniedKey.GetAccessControl()
  $acl.AddAccessRule($deny)
  $deniedKey.SetAccessControl($acl)
  try {
    Write-Output 'lifecycle-stage=denied-registry-write'
    $failed = Start-Process -FilePath $installerPath -ArgumentList '/S' -WorkingDirectory (Split-Path -Parent $installerPath) -WindowStyle Hidden -PassThru
    if (-not $failed.WaitForExit(180000)) { $failed.Kill(); throw 'Denied-write install timed out.' }
    $failed.Refresh()
    Write-Output "denied-registry-write-exit=$($failed.ExitCode)"
    Assert-True ($failed.ExitCode -ne 0) 'Denied registry write unexpectedly installed the product.'
    $setupLog = Join-Path $machineInstaller 'setup-rc6.log'
    Assert-True (Test-Path -LiteralPath $setupLog -PathType Leaf) 'Denied-write setup log missing.'
    Assert-True (([IO.File]::ReadAllText($setupLog)) -match 'journal-registry-invalidate') 'Denied-write error did not name registry-invalidate.'
    Copy-Item -LiteralPath $setupLog -Destination (Join-Path $EvidenceDir 'denied-write-setup.log')
  } finally {
    $acl.RemoveAccessRuleSpecific($deny)
    $deniedKey.SetAccessControl($acl)
    $deniedKey.Dispose()
  }
  $registry.DeleteSubKeyTree($rollbackPath, $false)
  Assert-True (-not (Test-Path -LiteralPath $shell)) 'Denied-write attempt mutated the live shell.'

  # A bounded fixture exercises the real handoff-origin hook. It is not a
  # signed catalog; the complete handoff is verified separately before release.
  $fixtureRoot = Split-Path -Parent $installerPath
  New-Item -ItemType Directory -Force -Path (Join-Path $fixtureRoot 'Catalog'),(Join-Path $fixtureRoot 'Components') | Out-Null
  Set-Content -LiteralPath (Join-Path $fixtureRoot 'Catalog\offline-catalog.json') -Value '{"fixture":"lifecycle-only; not a signed catalog"}' -NoNewline
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $sentinel) | Out-Null
  Set-Content -LiteralPath $sentinel -Value 'preserve across default uninstall' -NoNewline

  # RC.7 failed before mutating the live shell, leaving this exact durable
  # snapshotting record. RC.8 must validate and abandon it before retrying.
  $key = $registry.CreateSubKey($rollbackPath)
  try {
    $key.SetValue('TransactionId', '1234-5678')
    $key.SetValue('ExpectedVersion', '2.0.0-rc.7')
    $key.SetValue('PackageIdentity', 'rc6-sep4-installer-recovery-v1')
    $key.SetValue('CanonicalPath', $shell)
    $key.SetValue('StagingPath', $stage)
    $key.SetValue('BackupPath', $backup)
    $key.SetValue('Phase', 'snapshotting')
  } finally { $key.Dispose() }

  Write-Output 'lifecycle-stage=rc7-snapshot-recovery-install'
  $null = Invoke-Bounded $installerPath '/S' 'RC.7 residue recovery and first install'
  Assert-True (Test-Path -LiteralPath (Join-Path $shell 'ai-video-editor.exe') -PathType Leaf) 'Canonical executable missing.'
  $product = $registry.OpenSubKey($productPath)
  Assert-True ($null -ne $product) 'Product registration missing.'
  try {
    Assert-True ($product.GetValue('InstallCommitted') -eq 1) 'Install not committed.'
    Assert-True ($product.GetValue('PackageIdentity') -eq 'rc6-sep4-installer-recovery-v1') 'Package identity mismatch.'
  } finally { $product.Dispose() }
  $arp = $registry.OpenSubKey($arpPath)
  Assert-True ($null -ne $arp) 'ARP entry missing.'
  try { Assert-True ($arp.GetValue('InstallLocation') -eq $shell) 'ARP install location mismatch.' }
  finally { $arp.Dispose() }
  Assert-True (Test-Path -LiteralPath (Join-Path $env:Public 'Desktop\AI Video Editor Desktop V2.lnk')) 'All-users Desktop shortcut missing.'
  Assert-True (Test-Path -LiteralPath (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\AI Video Editor Desktop V2\AI Video Editor Desktop V2.lnk')) 'Start Menu shortcut missing.'
  Assert-True ($null -eq $registry.OpenSubKey($rollbackPath)) 'Install transaction key remains.'
  Assert-True (-not (Test-Path -LiteralPath $stage)) 'Staging directory remains.'
  Assert-True (-not (Test-Path -LiteralPath $backup)) 'Rollback directory remains.'
  $handoffOrigin = Join-Path $machineInstaller 'handoff-root.json'
  Assert-True (Test-Path -LiteralPath $handoffOrigin -PathType Leaf) 'Handoff origin missing.'
  $origin = Get-Content -LiteralPath $handoffOrigin -Raw | ConvertFrom-Json
  Assert-True ($origin.handoffRoot -eq $fixtureRoot.Replace('\','/')) 'Handoff origin path mismatch.'

  Write-Output 'lifecycle-stage=rc8-reinstall'
  Write-Output "pre-reinstall-shell-process-count=$(@(Get-Process -Name 'ai-video-editor' -ErrorAction SilentlyContinue).Count)"
  $probe = "$shell.rc8-ci-rename-probe"
  [IO.Directory]::Move($shell, $probe)
  try { Write-Output 'pre-reinstall-directory-move=passed' }
  finally { [IO.Directory]::Move($probe, $shell) }
  $null = Invoke-Bounded $installerPath '/S' 'RC.8 reinstall'
  Assert-True (Test-Path -LiteralPath (Join-Path $shell 'ai-video-editor.exe') -PathType Leaf) 'Reinstalled executable missing.'
  Write-Output 'lifecycle-stage=default-uninstall'
  $installedUninstaller = Join-Path $shell 'uninstall.exe'
  Assert-True (Test-Path -LiteralPath $installedUninstaller -PathType Leaf) 'Installed uninstaller missing.'
  $uninstallCopyDir = Join-Path $evidenceRoot ('uninstall-copy-' + [Guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $uninstallCopyDir | Out-Null
  $copiedUninstaller = Join-Path $uninstallCopyDir 'uninstall.exe'
  Copy-Item -LiteralPath $installedUninstaller -Destination $copiedUninstaller
  $installedUninstallerSha = (Get-FileHash -LiteralPath $installedUninstaller -Algorithm SHA256).Hash.ToLowerInvariant()
  $copiedUninstallerSha = (Get-FileHash -LiteralPath $copiedUninstaller -Algorithm SHA256).Hash.ToLowerInvariant()
  Assert-True ($copiedUninstallerSha -eq $installedUninstallerSha) 'Temporary uninstaller copy hash mismatch.'
  [pscustomobject]@{ sourceSha256=$installedUninstallerSha; copySha256=$copiedUninstallerSha; hashesMatch=$true } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $EvidenceDir 'copied-uninstaller-verification.json')
  # NSIS's _?= path is the final argument and is deliberately unquoted.
  $uninstallExit = Invoke-Bounded $copiedUninstaller ('/S _?=' + $shell) 'Default uninstall' $uninstallCopyDir (Join-Path $EvidenceDir 'copied-uninstaller-result.json')
  Write-Output "default-uninstall-exit=$uninstallExit"
  Assert-True (-not (Test-Path -LiteralPath $shell)) 'Canonical shell remains after uninstall.'
  Assert-True ($null -eq $registry.OpenSubKey($arpPath)) 'ARP entry remains after uninstall.'
  Assert-True ($null -eq $registry.OpenSubKey($productPath)) 'Product key remains after uninstall.'
  Assert-True ($null -eq $registry.OpenSubKey($rollbackPath)) 'Uninstall transaction remains.'
  Assert-True (-not (Test-Path -LiteralPath (Join-Path $env:Public 'Desktop\AI Video Editor Desktop V2.lnk'))) 'All-users Desktop shortcut remains after uninstall.'
  Assert-True (-not (Test-Path -LiteralPath (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\AI Video Editor Desktop V2\AI Video Editor Desktop V2.lnk'))) 'Start Menu shortcut remains after uninstall.'
  Assert-True (Test-Path -LiteralPath $sentinel -PathType Leaf) 'Default uninstall removed user data.'
  Assert-True (-not (Test-Path -LiteralPath $handoffOrigin)) 'Handoff origin remains after uninstall.'
  [pscustomobject]@{
    status='passed'; installerSha256=(Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    registryWriteFailure=$true; rc7SnapshotRecovery=$true; firstInstall=$true; reinstall=$true; defaultUninstall=$true; copiedUninstallerExitCode=$uninstallExit; userDataPreserved=$true
  } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $EvidenceDir 'actual-installer-lifecycle.json')
} catch {
  try {
    if (Test-Path -LiteralPath $parent -PathType Container) {
      $entries = @(Get-ChildItem -LiteralPath $parent -Force -Recurse -Depth 2 -ErrorAction SilentlyContinue |
        Select-Object -First 100 |
        ForEach-Object { [pscustomobject]@{ path=$_.FullName.Substring($parent.Length).TrimStart('\'); directory=$_.PSIsContainer; bytes=$(if ($_.PSIsContainer) { $null } else { $_.Length }) } })
      [pscustomobject]@{ shellExists=(Test-Path -LiteralPath $shell); entries=$entries; entryLimit=100; depthLimit=2 } |
        ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $EvidenceDir 'product-directory-on-failure.json')
    }
  } catch { Write-Warning "Could not save bounded product listing: $($_.Exception.Message)" }
  throw
} finally {
  foreach ($name in @('setup-rc6.log','uninstall-rc6.log','transaction-rc6.json','uninstall-transaction-rc6.json')) {
    $source = Join-Path $machineInstaller $name
    if (Test-Path -LiteralPath $source -PathType Leaf) { Copy-Item -LiteralPath $source -Destination $EvidenceDir -Force }
  }
  $registry.Dispose()
}
