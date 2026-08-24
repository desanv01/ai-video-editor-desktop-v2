[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)] [string]$HandoffRoot,
  [Parameter(Mandatory = $true)] [string]$EvidencePath,
  [string]$SourcePath
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $HandoffRoot).Path
$source = if ($SourcePath) { (Resolve-Path -LiteralPath $SourcePath).Path } else { Join-Path $root 'SMOKE\synthetic-source.mp4' }
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Smoke source is missing: $source" }
$staging = Join-Path ([IO.Path]::GetTempPath()) "aive-desktop-v2-smoke-$PID-$([Guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $staging -Force | Out-Null
try {
  $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
  $archives = @(Get-ChildItem -LiteralPath (Join-Path $root 'Components') -Filter '*.tar.gz' -File | Sort-Object Name)
  if (-not $tar -and $archives.Count -gt 0) { throw 'tar.exe is required to exercise packaged component archives.' }
  $archiveIndex = 0
  foreach ($archive in $archives) {
    $members = @(& $tar.Source -tzf $archive.FullName 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not list component archive: $($archive.Name)" }
    foreach ($member in $members) {
      $memberText = ([string]$member).Trim()
      if (-not $memberText) { continue }
      $memberText = $memberText.Replace('\', '/')
      if ([IO.Path]::IsPathRooted($memberText) -or $memberText.Split('/') -contains '..' -or $memberText.Contains(':')) {
        throw "Unsafe archive member rejected: $($archive.Name) -> $memberText"
      }
    }
    $destination = Join-Path $staging "archive-$archiveIndex"
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    & $tar.Source -xzf $archive.FullName -C $destination 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not extract component archive: $($archive.Name)" }
    $archiveIndex++
  }
  $searchRoots = @($staging, (Join-Path $root 'Components'))
  $ffmpeg = Get-ChildItem -Path $searchRoots -Recurse -Filter 'ffmpeg.exe' -File -ErrorAction SilentlyContinue | Select-Object -First 1
  $ffprobe = Get-ChildItem -Path $searchRoots -Recurse -Filter 'ffprobe.exe' -File -ErrorAction SilentlyContinue | Select-Object -First 1
  $engine = Get-ChildItem -Path $searchRoots -Recurse -Filter 'aive-engine.exe' -File -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $ffmpeg -or -not $ffprobe) { throw 'Required FFmpeg/ffprobe binaries are missing from packaged component archives.' }
  $output = Join-Path $staging 'encoded-smoke.mp4'
  $probe = & $ffprobe.FullName -v error -show_entries format=duration:stream=codec_name,width,height -of json $source 2>&1
  $probeExit = $LASTEXITCODE
  & $ffmpeg.FullName -hide_banner -loglevel error -y -i $source -t 1 -c:v libx264 -pix_fmt yuv420p $output 2>&1 | Out-Null
  $encodeExit = $LASTEXITCODE
  $decodeExit = 1
  if ($encodeExit -eq 0) { & $ffmpeg.FullName -hide_banner -loglevel error -i $output -f null - 2>&1 | Out-Null; $decodeExit = $LASTEXITCODE }
  $engineExit = $null
  $engineSelfTest = $null
  if ($engine) {
    $engineSelfTest = & $engine.FullName --self-test 2>&1
    $engineExit = $LASTEXITCODE
  }
  $payload = [ordered]@{
    schemaVersion = 'desktop.smoke-evidence.v1'
    source = $source.Substring($root.Length).TrimStart('\', '/')
    packagedArchivesInspected = @($archives | ForEach-Object { $_.Name })
    extractionRoot = 'disposable-temp; not retained'
    ffmpegPath = if ($ffmpeg) { 'disposable-extraction' } else { $null }
    ffprobePath = if ($ffprobe) { 'disposable-extraction' } else { $null }
    enginePath = if ($engine) { 'disposable-extraction' } else { $null }
    ffprobeExit = $probeExit
    ffprobe = ($probe -join "`n")
    encodeExit = $encodeExit
    decodeExit = $decodeExit
    engineSelfTestExit = $engineExit
    engineSelfTest = if ($engineSelfTest) { ($engineSelfTest -join "`n") } else { $null }
    restartReadiness = 'pending-external-clean-PC'
    repair = 'pending-external-clean-PC'
    uninstallPlanPreservation = 'covered-by-migration-unit-and-plan-tests; pending-external-clean-PC'
    note = 'This script verifies archive member safety, extracts packaged components to disposable temp storage, and proves local media probe/encode/decode plus engine self-test. It does not claim clean-PC install, restart, repair, or uninstall evidence.'
  }
  $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
  if ($probeExit -ne 0 -or $encodeExit -ne 0 -or $decodeExit -ne 0 -or ($engine -and $engineExit -ne 0)) { exit 60 }
  exit 0
} finally {
  Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
}
