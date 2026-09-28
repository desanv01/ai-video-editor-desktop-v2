[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$desktopRoot = Join-Path $repoRoot 'desktop'
$tauriCli = Join-Path $desktopRoot 'node_modules\.bin\tauri.cmd'
if (-not (Test-Path -LiteralPath $tauriCli -PathType Leaf)) {
  throw 'The local Tauri CLI is missing. Run npm ci in desktop first.'
}

Push-Location $desktopRoot
try {
  $buildOutput = @()
  # Tauri writes progress to stderr; capture it without PowerShell treating it
  # as a terminating error, then enforce the native exit code and warning gate.
  $ErrorActionPreference = 'Continue'
  & $tauriCli build --bundles nsis --no-sign 2>&1 | Tee-Object -Variable buildOutput
  $buildExit = $LASTEXITCODE
  $ErrorActionPreference = 'Stop'
  $buildText = $buildOutput | Out-String
  if ($buildText -match '(?im)warning\s+6000\b|unknown\s+variable\s*/\s*constant') {
    throw 'NSIS reported warning 6000 or an unknown variable/constant during the production installer build.'
  }
  if ($buildExit -ne 0) { throw "Tauri NSIS build failed with exit $buildExit." }

  & node --experimental-strip-types (Join-Path $PSScriptRoot 'verify-rendered-nsis.mjs')
  if ($LASTEXITCODE -ne 0) { throw 'The freshly rendered NSIS verification failed.' }
} finally {
  Pop-Location
}
