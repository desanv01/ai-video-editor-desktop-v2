[CmdletBinding()]
param([string]$EvidencePath)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-True([bool]$Condition, [string]$Message) {
  if (-not $Condition) { throw $Message }
}

function Assert-Equal($Actual, $Expected, [string]$Message) {
  if ($Actual -ne $Expected) { throw "$Message (expected '$Expected', got '$Actual')" }
}

function Get-FullPath([string]$Path) {
  return [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

$scriptRoot = Get-FullPath $PSScriptRoot
$harnessSource = Join-Path $scriptRoot 'nsis-state-matrix-harness.nsi'
$makensisCandidates = @(
  (Join-Path $env:LOCALAPPDATA 'tauri\NSIS\makensis.exe'),
  (Join-Path $env:LOCALAPPDATA 'tauri\NSIS\Bin\makensis.exe')
)
$makensis = $makensisCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $makensis) { throw 'Tauri makensis.exe is unavailable under %LOCALAPPDATA%\tauri\NSIS.' }

$tempBoundary = Get-FullPath (Join-Path ([IO.Path]::GetTempPath()) 'AIVE-Installer-StateMatrix')
$runToken = [Guid]::NewGuid().ToString('N')
$runRoot = Get-FullPath (Join-Path $tempBoundary $runToken)
Assert-True ($runRoot.StartsWith($tempBoundary + '\', [StringComparison]::OrdinalIgnoreCase)) 'Matrix root escaped the disposable TEMP boundary.'
New-Item -ItemType Directory -Path $runRoot | Out-Null

$registryBase = 'Software\AIVE Installer State Matrix'
$credentialBase = 'Software\AIVE Installer State Matrix Credentials'
$caseResults = [Collections.Generic.List[object]]::new()
$createdRegistryIds = [Collections.Generic.List[string]]::new()

function Get-Paths([string]$Root) {
  $parent = Join-Path $Root 'ProgramFiles\AI Video Editor Desktop V2'
  return [ordered]@{
    Shell = Join-Path $parent 'Shell'
    Stage = Join-Path $parent 'Shell.rc6-staging'
    Backup = Join-Path $parent 'Shell.rc6-rollback'
    Runtime = Join-Path $Root 'Runtime'
    UserData = Join-Path $Root 'UserData'
    Documents = Join-Path $Root 'Documents'
    Shortcuts = Join-Path $Root 'Shortcuts'
  }
}

function New-OwnedPayload([string]$Path, [string]$Tag, [switch]$Installing) {
  New-Item -ItemType Directory -Path $Path -Force | Out-Null
  Set-Content -LiteralPath (Join-Path $Path 'desktop-v2.identity.json') -Value "identity-$Tag" -NoNewline
  Set-Content -LiteralPath (Join-Path $Path 'ai-video-editor.exe') -Value "binary-$Tag" -NoNewline
  Set-Content -LiteralPath (Join-Path $Path 'uninstall.exe') -Value "uninstall-$Tag" -NoNewline
  Set-Content -LiteralPath (Join-Path $Path 'payload.dat') -Value "payload-$Tag" -NoNewline
  if ($Installing) { Set-Content -LiteralPath (Join-Path $Path '.installing') -Value owned -NoNewline }
}

function Set-Registration([string]$Id, [string]$InstallPath, [string]$Arp = 'present', [int]$Committed = 1) {
  $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("$registryBase\$Id")
  try {
    $key.SetValue('InstallPath', $InstallPath, [Microsoft.Win32.RegistryValueKind]::String)
    if ($null -ne $Arp) { $key.SetValue('Arp', $Arp, [Microsoft.Win32.RegistryValueKind]::String) }
    $key.SetValue('InstallCommitted', $Committed, [Microsoft.Win32.RegistryValueKind]::DWord)
  } finally { $key.Dispose() }
}

function Set-CredentialSentinel([string]$Id) {
  $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("$credentialBase\$Id")
  try { $key.SetValue('provider', 'preserve-me', [Microsoft.Win32.RegistryValueKind]::String) }
  finally { $key.Dispose() }
}

function Test-RegistryKey([string]$Base, [string]$Id) {
  $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("$Base\$Id")
  if ($null -eq $key) { return $false }
  $key.Dispose()
  return $true
}

function Read-Result([string]$Path) {
  $values = @{}
  foreach ($line in Get-Content -LiteralPath $Path) {
    $pair = $line -split '=', 2
    if ($pair.Count -eq 2) { $values[$pair[0]] = $pair[1] }
  }
  return $values
}

function Start-Harness([string]$Root, [string]$Case, [string]$Id, [string]$Result) {
  $process = Start-Process -FilePath $script:harnessExe -ArgumentList @("/AIVE_TEST_ROOT=$Root", "/AIVE_TEST_BOUNDARY=$script:tempBoundary", "/CASE=$Case", "/RUNID=$Id", "/RESULT=$Result") -Wait -PassThru -WindowStyle Hidden
  try { return $process.ExitCode }
  finally { $process.Dispose() }
}

function Invoke-Harness(
  [string]$Name,
  [string]$Case,
  [scriptblock]$Seed,
  [int]$ExpectedExit = 0,
  [string]$ExpectedState = '',
  [scriptblock]$Verify = $null
) {
  $id = [Guid]::NewGuid().ToString('N')
  $createdRegistryIds.Add($id)
  $root = Get-FullPath (Join-Path $runRoot $Name)
  Assert-True ($root.StartsWith($runRoot + '\', [StringComparison]::OrdinalIgnoreCase)) "$Name escaped the run root."
  New-Item -ItemType Directory -Path $root | Out-Null
  $paths = Get-Paths $root
  if ($Seed) { & $Seed $root $paths $id }
  $resultPath = Join-Path $root 'result.txt'
  $exitCode = Start-Harness $root $Case $id $resultPath
  if ($exitCode -ne $ExpectedExit) {
    throw ('{0} returned exit {1} (expected {2}); root={3}; expected boundary={4}; PowerShell TEMP={5}; result={6}' -f
      $Name, $exitCode, $ExpectedExit, $root, $script:tempBoundary, [IO.Path]::GetTempPath(), $resultPath)
  }
  Assert-True (Test-Path -LiteralPath $resultPath -PathType Leaf) "$Name did not write a result."
  $result = Read-Result $resultPath
  if ($ExpectedState) { Assert-Equal $result.state $ExpectedState "$Name returned the wrong state" }
  foreach ($unsafe in @($paths.Shell, $paths.Stage, $paths.Backup)) {
    Assert-True (-not [String]::Equals($result.outdir, $unsafe, [StringComparison]::OrdinalIgnoreCase)) "$Name left CWD at a rename/removal target: $unsafe"
  }
  if ($Verify) { & $Verify $root $paths $id $result }
  $caseResults.Add([pscustomobject]@{ name = $Name; case = $Case; exitCode = $exitCode; state = $result.state })
}

try {
  Copy-Item -LiteralPath $harnessSource -Destination (Join-Path $runRoot 'harness.nsi')
  Push-Location $runRoot
  try {
    & $makensis /V2 (Join-Path $runRoot 'harness.nsi')
    if ($LASTEXITCODE -ne 0) { throw "Tauri makensis failed with exit $LASTEXITCODE." }
  } finally { Pop-Location }
  $script:harnessExe = Join-Path $runRoot 'nsis-state-matrix-harness.exe'
  Assert-True (Test-Path -LiteralPath $script:harnessExe -PathType Leaf) 'Compiled NSIS harness is missing.'

  Invoke-Harness pristine classify-only {} 0 pristine
  Invoke-Harness empty-residue classify-only { param($r,$p) New-Item -ItemType Directory -Path $p.Shell -Force | Out-Null } 0 empty-owned-residue
  Invoke-Harness unknown-live classify-only { param($r,$p) New-Item -ItemType Directory -Path $p.Shell -Force | Out-Null; Set-Content -LiteralPath (Join-Path $p.Shell 'foreign.txt') -Value foreign } 0 unknown-nonempty-or-reparse
  Invoke-Harness valid-upgrade classify-only { param($r,$p,$id) New-OwnedPayload $p.Shell old; Set-Registration $id $p.Shell } 0 valid-committed
  Invoke-Harness missing-arp classify-only { param($r,$p,$id) New-OwnedPayload $p.Shell old; Set-Registration $id $p.Shell $null } 0 repairable-registration

  Invoke-Harness unknown-orphan-preserved install {
    param($r,$p) New-Item -ItemType Directory -Path $p.Shell -Force | Out-Null; Set-Content -LiteralPath (Join-Path $p.Shell 'foreign.txt') -Value foreign
  } 2112 conflict-preserved {
    param($r,$p) Assert-True (Test-Path -LiteralPath (Join-Path $p.Shell 'foreign.txt')) 'Unknown live orphan was modified.'
  }

  Invoke-Harness interrupted-staging recover-only {
    param($r,$p) New-OwnedPayload $p.Stage partial -Installing
  } 0 pristine { param($r,$p) Assert-True (-not (Test-Path -LiteralPath $p.Stage)) 'Interrupted staging survived recovery.' }
  Invoke-Harness interrupted-prior-move recover-only {
    param($r,$p,$id) New-OwnedPayload $p.Backup old; Set-Registration $id $p.Shell
  } 0 valid-committed { param($r,$p) Assert-Equal (Get-Content -LiteralPath (Join-Path $p.Shell 'payload.dat') -Raw) 'payload-old' 'Prior shell was not restored.' }
  Invoke-Harness interrupted-activation recover-only {
    param($r,$p,$id) New-OwnedPayload $p.Shell partial -Installing; New-OwnedPayload $p.Backup old; Set-Registration $id $p.Shell
  } 0 valid-committed { param($r,$p) Assert-Equal (Get-Content -LiteralPath (Join-Path $p.Shell 'payload.dat') -Raw) 'payload-old' 'Activation recovery did not restore old payload.' }
  Invoke-Harness interrupted-commit recover-only {
    param($r,$p,$id) New-OwnedPayload $p.Shell new; New-OwnedPayload $p.Backup old; Set-Registration $id $p.Shell
  } 0 valid-committed { param($r,$p) Assert-True (-not (Test-Path -LiteralPath $p.Backup)) 'Stale commit backup survived.' }
  Invoke-Harness stale-backup recover-only {
    param($r,$p,$id) New-OwnedPayload $p.Shell committed; New-OwnedPayload $p.Backup stale; Set-Registration $id $p.Shell
  } 0 valid-committed { param($r,$p) Assert-Equal (Get-Content -LiteralPath (Join-Path $p.Shell 'payload.dat') -Raw) 'payload-committed' 'Committed shell changed.' }
  Invoke-Harness unknown-backup recover-only {
    param($r,$p) New-Item -ItemType Directory -Path $p.Backup -Force | Out-Null; Set-Content -LiteralPath (Join-Path $p.Backup 'foreign.txt') -Value foreign
  } 2112 conflict-preserved { param($r,$p) Assert-True (Test-Path -LiteralPath (Join-Path $p.Backup 'foreign.txt')) 'Unknown backup was modified.' }

  foreach ($fault in @('fail-staging','fail-prior-move','fail-activation','fail-shortcut','fail-registration','fail-identity')) {
    Invoke-Harness "phase-$fault" $fault {
      param($r,$p,$id) New-OwnedPayload $p.Shell old; Set-Registration $id $p.Shell; New-Item -ItemType Directory -Path $p.Shortcuts -Force | Out-Null; Set-Content -LiteralPath (Join-Path $p.Shortcuts 'Desktop.lnk') old-desktop; Set-Content -LiteralPath (Join-Path $p.Shortcuts 'StartMenu.lnk') old-start
    } $(if ($fault -eq 'fail-activation') { 2106 } elseif ($fault -eq 'fail-shortcut') { 2103 } elseif ($fault -eq 'fail-registration') { 2108 } elseif ($fault -eq 'fail-identity') { 2109 } else { 2104 }) "fault-$($fault.Substring(5))" {
      param($r,$p,$id)
      Assert-Equal (Get-Content -LiteralPath (Join-Path $p.Shell 'payload.dat') -Raw) 'payload-old' 'Fault rollback lost old shell.'
      Assert-True (-not (Test-Path -LiteralPath $p.Stage)) 'Fault rollback left staging.'
      Assert-True (-not (Test-Path -LiteralPath $p.Backup)) 'Fault rollback left backup.'
      Assert-True (Test-RegistryKey $registryBase $id) 'Fault rollback lost prior registration.'
      Assert-Equal (Get-Content -LiteralPath (Join-Path $p.Shortcuts 'Desktop.lnk') -Raw).Trim() 'old-desktop' 'Desktop shortcut was not restored.'
    }
  }

  Invoke-Harness failed-fresh-cleanup fail-registration {} 2108 fault-registration {
    param($r,$p,$id) Assert-True (-not (Test-Path -LiteralPath $p.Shell) -and -not (Test-Path -LiteralPath $p.Stage) -and -not (Test-RegistryKey $registryBase $id)) 'Fresh failure left owned state.'
  }

  $lockId = [Guid]::NewGuid().ToString('N'); $createdRegistryIds.Add($lockId)
  $lockRoot = Get-FullPath (Join-Path $runRoot 'locked-update'); New-Item -ItemType Directory -Path $lockRoot | Out-Null; $lockPaths = Get-Paths $lockRoot
  New-OwnedPayload $lockPaths.Shell old; Set-Registration $lockId $lockPaths.Shell
  $lockStream = [IO.File]::Open((Join-Path $lockPaths.Shell 'ai-video-editor.exe'), [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
  try {
    $lockResult = Join-Path $lockRoot 'result.txt'; $lockExit = Start-Harness $lockRoot install $lockId $lockResult; Assert-Equal $lockExit 2105 'Locked update was not refused'; $parsed = Read-Result $lockResult; Assert-Equal $parsed.state lock-refused 'Locked update state mismatch'; Assert-Equal (Get-Content -LiteralPath (Join-Path $lockPaths.Shell 'payload.dat') -Raw) 'payload-old' 'Locked update changed old shell'; $caseResults.Add([pscustomobject]@{name='locked-update';case='install';exitCode=2105;state=$parsed.state})
  } finally { $lockStream.Dispose() }

  $concurrentId = [Guid]::NewGuid().ToString('N'); $createdRegistryIds.Add($concurrentId)
  $concurrentRoot = Get-FullPath (Join-Path $runRoot 'concurrent'); New-Item -ItemType Directory -Path $concurrentRoot | Out-Null
  $firstResult = Join-Path $concurrentRoot 'first.txt'; $secondResult = Join-Path $concurrentRoot 'second.txt'
  $first = Start-Process -FilePath $script:harnessExe -ArgumentList @("/AIVE_TEST_ROOT=$concurrentRoot","/AIVE_TEST_BOUNDARY=$script:tempBoundary",'/CASE=hold-mutex',"/RUNID=$concurrentId","/RESULT=$firstResult") -PassThru -WindowStyle Hidden
  try {
    Start-Sleep -Milliseconds 400
    $secondExit = Start-Harness $concurrentRoot classify-only $concurrentId $secondResult
    Assert-Equal $secondExit 2113 'Concurrent invocation was not refused'
    Assert-Equal (Read-Result $secondResult).state concurrent-refused 'Concurrent state mismatch'
    $first.WaitForExit(); Assert-Equal $first.ExitCode 0 'Mutex holder failed'
    $caseResults.Add([pscustomobject]@{name='concurrent';case='mutex';exitCode=2113;state='concurrent-refused'})
  } finally { if (-not $first.HasExited) { $first.Kill(); $first.WaitForExit() }; $first.Dispose() }

  $seedUninstall = {
    param($r,$p,$id)
    New-OwnedPayload $p.Shell installed; Set-Registration $id $p.Shell; Set-CredentialSentinel $id
    foreach ($dir in @($p.Runtime,(Join-Path $p.UserData 'Config'),(Join-Path $p.UserData 'uploads'),(Join-Path $p.UserData 'models'),(Join-Path $p.UserData 'database'),(Join-Path $p.Documents 'Projects'),(Join-Path $p.Documents 'Exports'))) { New-Item -ItemType Directory -Path $dir -Force | Out-Null; Set-Content -LiteralPath (Join-Path $dir 'sentinel.txt') -Value keep }
    Set-Content -LiteralPath (Join-Path $p.UserData 'unknown.txt') -Value unknown
  }
  Invoke-Harness uninstall-default uninstall-default $seedUninstall 0 uninstalled-preserve-data {
    param($r,$p,$id) Assert-True (-not (Test-Path -LiteralPath $p.Shell) -and -not (Test-Path -LiteralPath $p.Runtime)) 'Default uninstall left owned runtime.'; Assert-True (Test-Path -LiteralPath (Join-Path $p.UserData 'Config\sentinel.txt')) 'Default uninstall removed user data.'; Assert-True (Test-RegistryKey $credentialBase $id) 'Default uninstall removed credentials.'
  }
  Invoke-Harness uninstall-full-wipe uninstall-full-wipe $seedUninstall 0 uninstalled-full-wipe {
    param($r,$p,$id) Assert-True (-not (Test-Path -LiteralPath (Join-Path $p.UserData 'Config')) -and -not (Test-Path -LiteralPath (Join-Path $p.Documents 'Projects'))) 'Full wipe retained allowlisted data.'; Assert-True (-not (Test-RegistryKey $credentialBase $id)) 'Full wipe retained known credentials.'; Assert-True (Test-Path -LiteralPath (Join-Path $p.UserData 'unknown.txt')) 'Full wipe removed unknown data.'
  }

  $uninstallLockId = [Guid]::NewGuid().ToString('N'); $createdRegistryIds.Add($uninstallLockId)
  $uninstallLockRoot = Get-FullPath (Join-Path $runRoot 'uninstall-locked'); New-Item -ItemType Directory -Path $uninstallLockRoot | Out-Null; $uninstallLockPaths = Get-Paths $uninstallLockRoot
  & $seedUninstall $uninstallLockRoot $uninstallLockPaths $uninstallLockId
  $uninstallStream = [IO.File]::Open((Join-Path $uninstallLockPaths.Shell 'ai-video-editor.exe'), [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
  try {
    $resultPath = Join-Path $uninstallLockRoot 'result.txt'; $uninstallExit = Start-Harness $uninstallLockRoot uninstall-locked $uninstallLockId $resultPath; Assert-Equal $uninstallExit 2105 'Locked uninstall was not reported'; Assert-Equal (Read-Result $resultPath).state uninstall-lock-preserved 'Locked uninstall state mismatch'; Assert-True (Test-Path -LiteralPath $uninstallLockPaths.Shell) 'Locked uninstall removed the live directory'; $caseResults.Add([pscustomobject]@{name='uninstall-locked';case='uninstall';exitCode=2105;state='uninstall-lock-preserved'})
  } finally { $uninstallStream.Dispose() }

  $outside = Get-FullPath (Join-Path ([IO.Path]::GetTempPath()) ('aive-rejected-' + [Guid]::NewGuid().ToString('N')))
  $outsideResult = Join-Path $outside 'result.txt'
  $outsideExit = Start-Harness $outside classify-only rejected $outsideResult
  Assert-Equal $outsideExit 2111 'Out-of-bound root was not rejected'
  Assert-True (-not (Test-Path -LiteralPath $outside)) 'Rejected root was created or written.'
  $caseResults.Add([pscustomobject]@{name='reject-outside-temp-boundary';case='safety';exitCode=2111;state='rejected-root'})

  $evidence = [pscustomobject]@{ status='pass'; schemaVersion='desktop.nsis-state-matrix.v1'; makensis=(& $makensis /VERSION); cases=$caseResults.Count; results=$caseResults }
  $evidenceJson = $evidence | ConvertTo-Json -Depth 5
  if ($EvidencePath) {
    $resolvedEvidence = [IO.Path]::GetFullPath($EvidencePath)
    $evidenceParent = Split-Path -Parent $resolvedEvidence
    New-Item -ItemType Directory -Path $evidenceParent -Force | Out-Null
    Set-Content -LiteralPath $resolvedEvidence -Value $evidenceJson -Encoding utf8
  }
  Write-Output $evidenceJson
} finally {
  foreach ($id in $createdRegistryIds) {
    [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree("$registryBase\$id", $false)
    [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree("$credentialBase\$id", $false)
  }
  $resolvedCleanup = Get-FullPath $runRoot
  if ($resolvedCleanup.StartsWith($tempBoundary + '\', [StringComparison]::OrdinalIgnoreCase) -and $resolvedCleanup -ne $tempBoundary -and (Test-Path -LiteralPath $resolvedCleanup)) {
    for ($attempt = 0; $attempt -lt 10 -and (Test-Path -LiteralPath $resolvedCleanup); $attempt += 1) {
      try { Remove-Item -LiteralPath $resolvedCleanup -Recurse -Force -ErrorAction Stop }
      catch { Start-Sleep -Milliseconds 200 }
    }
    if (Test-Path -LiteralPath $resolvedCleanup) { throw "Could not remove disposable matrix root: $resolvedCleanup" }
  }
}
