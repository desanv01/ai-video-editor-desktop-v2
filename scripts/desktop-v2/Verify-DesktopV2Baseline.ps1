[CmdletBinding()]
param(
    [int64]$LargeFileBytes = 50MB
)

# Read-only Phase 0 guard. It reports state and scans source names/content; it
# never writes, deletes, installs, stages, or modifies repository files.
$ErrorActionPreference = "Stop"
# PowerShell 7 can promote native stderr (including Git's autocrlf warning) to
# a terminating ErrorRecord. The audit relies on exit codes and remains
# read-only, so keep native stderr from changing the verdict.
$PSNativeCommandUseErrorActionPreference = $false

function Normalize-Path([string]$PathValue) {
    return [System.IO.Path]::GetFullPath($PathValue).TrimEnd('\', '/')
}

function Test-SameOrChildPath([string]$Candidate, [string]$Root) {
    $candidatePath = Normalize-Path $Candidate
    $rootPath = Normalize-Path $Root
    return [System.String]::Equals($candidatePath, $rootPath, [System.StringComparison]::OrdinalIgnoreCase) -or
        $candidatePath.StartsWith($rootPath + '\', [System.StringComparison]::OrdinalIgnoreCase) -or
        $candidatePath.StartsWith($rootPath + '/', [System.StringComparison]::OrdinalIgnoreCase)
}

function Add-Failure([string]$Message) {
    $script:Failures += $Message
    Write-Host "FAIL: $Message" -ForegroundColor Red
}

function Invoke-Git([string[]]$Arguments) {
    # Git may emit harmless autocrlf guidance on stderr for a dirty worktree.
    # Preserve the exit-code checks while keeping the read-only audit stable.
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = @(& git -C $script:RepoRoot @Arguments 2>$null)
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return [pscustomobject]@{
        Output = $output
        ExitCode = $code
    }
}

function Get-RelativePath([string]$PathValue) {
    $fullPath = Normalize-Path $PathValue
    $rootWithSlash = (Normalize-Path $script:RepoRoot) + '\'
    return $fullPath.Substring($rootWithSlash.Length).Replace('\', '/')
}

function Test-ExcludedScanPath([string]$RelativePath) {
    $parts = $RelativePath.Split('/')
    $excluded = @('.git', 'node_modules', 'target', 'dist', 'build', '.venv', 'venv', '__pycache__', '.pytest_cache', '.vite', 'tmp', 'tmp_')
    foreach ($part in $parts) {
        if ($excluded -contains $part) { return $true }
    }
    return $false
}

$script:Failures = @()
$scriptRoot = Normalize-Path $PSScriptRoot
$script:RepoRoot = Normalize-Path (Join-Path $scriptRoot '..\..')
$currentPath = Normalize-Path (Get-Location).Path

$protectedPaths = @(
    'C:\Users\Dv\Desktop\ai-video-editor',
    'C:\Users\Dv\Desktop\ai-video-editor-viva-clean',
    'C:\Users\Dv\Desktop\ai-video-editor-standalone-release-work'
)

Write-Host 'Desktop V2 Phase 0 read-only verification'
Write-Host "Current directory: $currentPath"
Write-Host "Resolved repository: $script:RepoRoot"

foreach ($protectedPath in $protectedPaths) {
    if (Test-SameOrChildPath $currentPath $protectedPath) {
        Add-Failure "Current directory is protected: $protectedPath"
    }
    if (Test-SameOrChildPath $script:RepoRoot $protectedPath) {
        Add-Failure "Resolved repository is protected: $protectedPath"
    }
}

$rootCheck = Invoke-Git @('rev-parse', '--show-toplevel')
if ($rootCheck.ExitCode -ne 0) {
    Add-Failure 'Git repository could not be resolved from the supplied worktree.'
} else {
    $reportedRoot = Normalize-Path (($rootCheck.Output | Select-Object -First 1).ToString())
    if (-not [System.String]::Equals($reportedRoot, $script:RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        Add-Failure "Git root does not match script root: $reportedRoot"
    }
}

$branch = Invoke-Git @('branch', '--show-current')
$head = Invoke-Git @('rev-parse', 'HEAD')
$status = Invoke-Git @('status', '--short', '--branch')
$remote = Invoke-Git @('remote', '-v')
Write-Host ("Branch: " + (($branch.Output | Select-Object -First 1).ToString() -replace '^$', '(detached)'))
Write-Host ("HEAD: " + (($head.Output | Select-Object -First 1).ToString()))
Write-Host "Status:"
if ($status.Output.Count -gt 0) { $status.Output | ForEach-Object { Write-Host "  $_" } } else { Write-Host '  (clean)' }
Write-Host "Remote:"
$remote.Output | ForEach-Object { Write-Host "  $_" }

$requiredPaths = @(
    'README.md',
    'backend/app/main.py',
    'backend/tests',
    'desktop/package.json',
    'desktop/package-lock.json',
    'desktop/src-tauri/Cargo.toml',
    'desktop/src-tauri/Cargo.lock',
    'docker-compose.yml',
    'docker-compose.desktop.yml',
    'docs/desktop-v2/PHASE_0_BASELINE.md',
    'docs/desktop-v2/MASTER_IMPLEMENTATION_PLAN.md',
    'docs/desktop-v2/WORKSPACE_SAFETY.md'
)
foreach ($relativePath in $requiredPaths) {
    if (-not (Test-Path -LiteralPath (Join-Path $script:RepoRoot $relativePath))) {
        Add-Failure "Required baseline path is missing: $relativePath"
    }
}

$trackedResult = Invoke-Git @('ls-files', '--cached', '--others', '--exclude-standard', '--full-name')
if ($trackedResult.ExitCode -ne 0) {
    Add-Failure 'Git source inventory could not be read.'
    $trackedPaths = @()
} else {
    $trackedPaths = @($trackedResult.Output | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ })
}
Write-Host ("Visible source inventory entries: " + $trackedPaths.Count)

$secretNamePattern = '(^|/)(\.env(\..*)?|id_rsa|id_ed25519|credentials?\.(json|ya?ml|toml)|.*\.(pem|key|p12|pfx|crt|secrets?))$'
$secretCandidates = @()
foreach ($relativePath in $trackedPaths) {
    $normalized = $relativePath.Replace('\', '/')
    if ($normalized -match $secretNamePattern -and $normalized -ne '.env.example') {
        $secretCandidates += $normalized
    }
}
foreach ($knownSecretPath in @('.env', '.env.local', '.env.production', 'backend/.env', 'desktop/.env')) {
    if (Test-Path -LiteralPath (Join-Path $script:RepoRoot $knownSecretPath)) {
        $normalized = $knownSecretPath.Replace('\', '/')
        if ($secretCandidates -notcontains $normalized) { $secretCandidates += $normalized }
    }
}

# Scan source text for high-confidence live-token shapes, reporting filenames
# only so a failure cannot echo credential contents into the terminal.
$rg = Get-Command rg -ErrorAction SilentlyContinue
if ($null -ne $rg) {
    $secretExpressions = @('sk-[A-Za-z0-9]{16,}', 'AKIA[A-Z0-9]{16,}', 'gh[pousr]_[A-Za-z0-9]{20,}', '-----BEGIN .* PRIVATE KEY-----')
    $rgArgs = @('-l', '-I', '--no-messages', '--hidden', '--glob', '!.git/**', '--glob', '!**/node_modules/**', '--glob', '!**/target/**', '--glob', '!**/dist/**', '--glob', '!**/build/**', '--glob', '!**/.venv/**', '--glob', '!**/__pycache__/**')
    foreach ($expression in $secretExpressions) { $rgArgs += @('-e', $expression) }
    $rgArgs += @('--', $script:RepoRoot)
    $contentMatches = @(& $rg.Source @rgArgs 2>$null)
    if ($LASTEXITCODE -eq 0) {
        foreach ($match in $contentMatches) {
            $relative = Get-RelativePath $match
            if ($relative -ne '.env.example' -and $relative -ne 'scripts/desktop-v2/Verify-DesktopV2Baseline.ps1' -and $secretCandidates -notcontains $relative) {
                $secretCandidates += $relative
            }
        }
    }
}

if ($secretCandidates.Count -gt 0) {
    Add-Failure ("Secret-like file/content candidates detected (filenames only): " + (($secretCandidates | Sort-Object -Unique) -join ', '))
} else {
    Write-Host 'Secret scan: PASS'
}

$scanPaths = @()
if ($null -ne $rg) {
    $fileArgs = @('--files', '--hidden', '--no-ignore', '--glob', '!.git/**', '--glob', '!**/node_modules/**', '--glob', '!**/target/**', '--glob', '!**/dist/**', '--glob', '!**/build/**', '--glob', '!**/.venv/**', '--glob', '!**/venv/**', '--glob', '!**/__pycache__/**', '--glob', '!**/.pytest_cache/**', '--glob', '!**/.vite/**', '--glob', '!**/tmp/**', '--glob', '!**/tmp_*/**', $script:RepoRoot)
    $scanPaths = @(& $rg.Source @fileArgs 2>$null | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ })
} else {
    $scanPaths = $trackedPaths | ForEach-Object { Join-Path $script:RepoRoot $_ }
}

$largeCandidates = @()
foreach ($pathValue in $scanPaths) {
    if (-not (Test-Path -LiteralPath $pathValue -PathType Leaf)) { continue }
    $relative = Get-RelativePath $pathValue
    if (Test-ExcludedScanPath $relative) { continue }
    $length = (Get-Item -LiteralPath $pathValue).Length
    if ($length -gt $LargeFileBytes) {
        $largeCandidates += ("{0} ({1} bytes)" -f $relative, $length)
    }
}
if ($largeCandidates.Count -gt 0) {
    Add-Failure ("Large source/runtime artifacts over $LargeFileBytes bytes: " + ($largeCandidates -join ', '))
} else {
    Write-Host ("Large-artifact scan: PASS (threshold $LargeFileBytes bytes; dependency/build caches excluded)")
}

$runtimeTracked = @($trackedPaths | ForEach-Object { $_.Replace('\', '/') } | Where-Object {
    (($_ -match '(^|/)(uploads|data|output|runtime|node_modules|target|dist|build)(/|$)') -and $_ -notmatch '^backend/app/') -or
    $_ -match '(^|/)[^/]*\.(gguf|safetensors|onnx|ckpt|pth)$' -or
    ($_ -match '(^|/)(runtime|output|export|artifact|bundle)[^/]*\.(zip|7z|tar|gz|mp4|mov|wav|db)$' -and $_ -ne 'docs/fyp_context_pack.zip')
})
if ($runtimeTracked.Count -gt 0) {
    Add-Failure ("Runtime/private paths appear in the Git-visible inventory: " + ($runtimeTracked -join ', '))
} else {
    Write-Host 'Runtime/private tracked-path scan: PASS'
}

$diffCheck = Invoke-Git @('diff', '--check')
if ($diffCheck.ExitCode -ne 0) {
    Add-Failure ('git diff --check failed: ' + (($diffCheck.Output | Out-String).Trim()))
} else {
    Write-Host 'Static whitespace check: PASS'
}

if ($script:Failures.Count -gt 0) {
    Write-Host ("VERDICT: FAIL ($($script:Failures.Count) finding(s))") -ForegroundColor Red
    exit 1
}

Write-Host 'VERDICT: PASS' -ForegroundColor Green
exit 0
