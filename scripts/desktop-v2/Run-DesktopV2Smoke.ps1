[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)] [string]$HandoffRoot,
  [Parameter(Mandatory = $true)] [string]$EvidencePath,
  [string]$SourcePath
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $HandoffRoot).Path
$source = if ($SourcePath) { (Resolve-Path -LiteralPath $SourcePath).Path } else { Join-Path $root 'SMOKE\synthetic-source.mp4' }
$ffmpeg = Get-ChildItem -LiteralPath (Join-Path $root 'Components') -Recurse -Filter 'ffmpeg.exe' -File | Select-Object -First 1
$ffprobe = Get-ChildItem -LiteralPath (Join-Path $root 'Components') -Recurse -Filter 'ffprobe.exe' -File | Select-Object -First 1
$engine = Get-ChildItem -LiteralPath (Join-Path $root 'Components') -Recurse -Filter 'aive-engine.exe' -File | Select-Object -First 1
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Smoke source is missing: $source" }
if (-not $ffmpeg -or -not $ffprobe) { throw 'Required FFmpeg/ffprobe binaries are missing from the handoff.' }
$output = Join-Path ([IO.Path]::GetTempPath()) "aive-desktop-v2-smoke-$PID.mp4"
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
  source = [IO.Path]::GetRelativePath($root, $source)
  ffprobeExit = $probeExit
  ffprobe = ($probe -join "`n")
  encodeExit = $encodeExit
  decodeExit = $decodeExit
  engineSelfTestExit = $engineExit
  engineSelfTest = if ($engineSelfTest) { ($engineSelfTest -join "`n") } else { $null }
  restartReadiness = 'pending-external-clean-PC'
  repair = 'pending-external-clean-PC'
  uninstallPlanPreservation = 'covered-by-migration-unit-and-plan-tests; pending-external-clean-PC'
  note = 'This script proves local media probe/encode/decode and engine self-test when artifacts are present. It does not claim clean-PC install, restart, repair, or uninstall evidence.'
}
$payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
Remove-Item -LiteralPath $output -Force -ErrorAction SilentlyContinue
if ($probeExit -ne 0 -or $encodeExit -ne 0 -or $decodeExit -ne 0 -or ($engine -and $engineExit -ne 0)) { exit 60 }
exit 0
