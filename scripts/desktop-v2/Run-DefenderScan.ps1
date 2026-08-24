[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)] [string]$ScanPath,
  [Parameter(Mandatory = $true)] [string]$EvidencePath,
  [switch]$RequireDefender
)

$ErrorActionPreference = 'Stop'
$resolvedScan = (Resolve-Path -LiteralPath $ScanPath).Path
$started = Get-Date
$status = Get-MpComputerStatus -ErrorAction SilentlyContinue
if (-not $status) {
  $payload = [ordered]@{ schemaVersion = 'desktop.av-scan.v1'; status = 'unavailable'; scanPath = '<handoff-root>'; startedAt = $started.ToUniversalTime().ToString('o'); detail = 'Microsoft Defender cmdlets are unavailable on this validation host.'; detections = @(); zeroDetectionsClaimed = $false }
  $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
  if ($RequireDefender) { exit 40 }
  exit 0
}

Update-MpSignature -ErrorAction SilentlyContinue
$scan = Start-MpScan -ScanPath $resolvedScan -ScanType Custom -AsJob -ErrorAction Stop
$scan | Wait-Job | Out-Null
$result = Receive-Job $scan -ErrorAction SilentlyContinue
$detections = @(Get-MpThreatDetection -ErrorAction SilentlyContinue | Where-Object { $_.InitialDetectionTime -ge $started }) | ForEach-Object { $_.ThreatID }
$payload = [ordered]@{ schemaVersion = 'desktop.av-scan.v1'; status = if ($detections.Count) { 'detections-found' } else { 'completed' }; scanPath = '<handoff-root>'; startedAt = $started.ToUniversalTime().ToString('o'); finishedAt = (Get-Date).ToUniversalTime().ToString('o'); defenderSignatureVersion = $status.AntivirusSignatureVersion; detections = $detections; zeroDetectionsClaimed = $false; note = 'A clean local scan is evidence for this host only; it is not a promise of zero detections across vendors.' }
$payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
if ($detections.Count) { exit 41 }
exit 0
