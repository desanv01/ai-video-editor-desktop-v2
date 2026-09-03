[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)] [string]$HandoffRoot,
  [Parameter(Mandatory = $true)] [string]$EvidencePath,
  [string]$SourcePath
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $HandoffRoot).Path
$source = if ($SourcePath) { (Resolve-Path -LiteralPath $SourcePath).Path } else { $null }
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
  if (-not $ffmpeg -or -not $ffprobe -or -not $engine) { throw 'The packaged engine, FFmpeg, or ffprobe binary is missing from the component archives.' }
  $productRunner = Join-Path $root 'SMOKE\rc6-native-product-e2e.py'
  if (-not (Test-Path -LiteralPath $productRunner -PathType Leaf)) { throw "The RC.6 product E2E runner is missing: $productRunner" }
  $python = Get-Command python.exe -ErrorAction SilentlyContinue
  if (-not $python) { throw 'Python 3 is required only for this handoff smoke harness; it is not an installed-app prerequisite.' }
  $productRoot = Join-Path $staging 'redirected-product-root'
  $productEvidencePath = Join-Path $staging 'product-e2e.json'
  $productStdout = @(& $python.Source $productRunner --engine $engine.FullName --ffmpeg $ffmpeg.FullName --ffprobe $ffprobe.FullName --data-root $productRoot --evidence $productEvidencePath 2>&1)
  $productExit = $LASTEXITCODE
  if ($productExit -ne 0) { throw "Packaged product E2E failed with exit $productExit`: $($productStdout -join "`n")" }
  $productEvidence = Get-Content -LiteralPath $productEvidencePath -Raw | ConvertFrom-Json
  if (-not $source) { $source = Join-Path $productRoot 'Temp\rc6-e2e-source.mp4' }
  if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Smoke source is missing: $source" }
  $output = Join-Path $staging 'encoded-smoke.mp4'
  $probe = & $ffprobe.FullName -v error -show_entries format=duration:stream=codec_name,width,height -of json $source 2>&1
  $probeExit = $LASTEXITCODE
  & $ffmpeg.FullName -hide_banner -loglevel error -y -i $source -t 1 -c:v libx264 -pix_fmt yuv420p $output 2>&1 | Out-Null
  $encodeExit = $LASTEXITCODE
  $decodeExit = 1
  if ($encodeExit -eq 0) { & $ffmpeg.FullName -hide_banner -loglevel error -i $output -f null - 2>&1 | Out-Null; $decodeExit = $LASTEXITCODE }
  $engineSelfTest = & $engine.FullName --self-test 2>&1
  $engineExit = $LASTEXITCODE
  $evidenceParent = Split-Path -Parent $EvidencePath
  if ($evidenceParent) { New-Item -ItemType Directory -Path $evidenceParent -Force | Out-Null }
  $payload = [ordered]@{
    schemaVersion = 'desktop.smoke-evidence.v1'
    releaseVersion = '2.0.0-rc.6'
    artifactKind = 'actual-component-archives-extracted-to-disposable-temp'
    source = if ($SourcePath) { 'caller-supplied-valid-media' } else { 'generated-valid-mp4-in-redirected-root' }
    packagedArchivesInspected = @($archives | ForEach-Object { $_.Name })
    extractionRoot = 'disposable-temp; not retained'
    ffmpegPath = if ($ffmpeg) { 'disposable-extraction' } else { $null }
    ffprobePath = if ($ffprobe) { 'disposable-extraction' } else { $null }
    enginePath = 'disposable-extraction'
    ffprobeExit = $probeExit
    ffprobe = ($probe -join "`n")
    encodeExit = $encodeExit
    decodeExit = $decodeExit
    engineSelfTestExit = $engineExit
    engineSelfTest = ($engineSelfTest -join "`n")
    productE2E = $productEvidence
    redirectedRootRestartPersistence = if ($productEvidence.status -eq 'pass') { 'passed' } else { 'failed' }
    cleanPcInstall = 'not-tested'
    repair = 'not-tested'
    uninstall = 'not-tested'
    note = 'This operator smoke safely extracts the actual packaged archives and proves project creation, durable native MP4 import, provider-free process/export, playable output, engine restart, and redirected-root persistence. It does not install the shell and does not claim clean-PC install, UAC, shortcut, repair, or uninstall evidence.'
  }
  $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
  if ($productExit -ne 0 -or $probeExit -ne 0 -or $encodeExit -ne 0 -or $decodeExit -ne 0 -or $engineExit -ne 0) { exit 60 }
  exit 0
} finally {
  Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
}
