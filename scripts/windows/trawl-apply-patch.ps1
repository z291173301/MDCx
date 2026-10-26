#Requires -Version 3.0
<#
.SYNOPSIS
    Apply the MDCx TRAWL goto-timeout patch.

.DESCRIPTION
    Raises the Tier 3/4 page-load timeout ceiling from 30s to 90s, which makes
    MDCx's camoufox challenge solving far more reliable.

    Two strategies are tried, in order, so an upstream refactor can never break
    either the GitHub Actions package build or the end-user runtime launcher:

      1. `git apply` with the curated, hand-written patch file
         (packages/tiers/src/tiers/browser.ts and
          packages/tiers/src/utils/metaRefresh.ts on v1.8.0+, the old inline
          logic in 3.ts/4.ts on v1.4.0).
      2. A rule-based rewrite of the tier sources: every `timeout:` line that
         caps a page navigation with `Math.min(..., 30_000)` is bumped to
         90_000. Layout-independent, so it keeps working when trawl
         reorganises the tier code again.

    This script never returns a non-zero exit code. An unpatched TRAWL is still
    functional, so a best-effort patch must never fail the caller.

    NOTE: keep this file ASCII-only. PowerShell 5.1 reads .ps1 files without a
    BOM using the system ANSI code page, so any non-ASCII byte can turn into a
    parse error on a machine with a different locale. User-facing Chinese text
    lives in start-trawl.bat and the workflow YAML instead.

.PARAMETER SrcDir
    Path to the cloned trawl working tree. Defaults to `trawl-src` in the
    current directory.

.PARAMETER PatchFile
    Path to the .patch file. Defaults to
    `<SrcDir>\..\scripts\windows\trawl-goto-timeout.patch`.

.PARAMETER SearchRoots
    Sub-directories of SrcDir to scan for the rule-based fallback. The tier
    browser logic lives in `packages\tiers\src` in both the old and the new
    upstream layout.

.PARAMETER TimeoutMs
    Desired timeout ceiling, written exactly as it must appear in the source.
    Defaults to `90_000` (underscored, matching the upstream style).

.PARAMETER LegacyMs
    Upstream timeout ceiling to replace, as it appears in the source.
    Defaults to `30_000`.

.EXAMPLE
    .\trawl-apply-patch.ps1 -SrcDir trawl-src

.EXAMPLE
    powershell -File trawl-apply-patch.ps1 -SrcDir "%CD%\src" -PatchFile "%CD%\trawl-goto-timeout.patch"
#>
[CmdletBinding()]
param(
    [string] $SrcDir = "trawl-src",
    [string] $PatchFile,
    [string[]] $SearchRoots = @("packages\tiers\src"),
    [string] $TimeoutMs = "90_000",
    [string] $LegacyMs = "30_000"
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Resolve-FullPath {
    param(
        [string] $Path,
        [string] $Base
    )
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    if ([IO.Path]::IsPathRooted($Path)) { return [IO.Path]::GetFullPath($Path) }
    return [IO.Path]::GetFullPath((Join-Path $Base $Path))
}

# All *.ts files under the search roots. Returned as full paths so a file can
# be rewritten in place without touching anything else.
function Get-TierFiles {
    param([string] $Base)
    foreach ($root in $SearchRoots) {
        $rootPath = Join-Path $Base $root
        if (-not (Test-Path -LiteralPath $rootPath -PathType Container)) { continue }
        Get-ChildItem -LiteralPath $rootPath -Recurse -File -Filter "*.ts"
    }
}

$invocationDir = (Get-Location).Path
$src = Resolve-FullPath -Path $SrcDir -Base $invocationDir

if (-not (Test-Path -LiteralPath $src -PathType Container)) {
    Write-Warning "trawl source directory not found: $src"
    exit 0
}

if ($PatchFile) {
    $patch = Resolve-FullPath -Path $PatchFile -Base $invocationDir
}
else {
    $patch = Join-Path (Split-Path -Parent $src) "scripts\windows\trawl-goto-timeout.patch"
}

# ---------------------------------------------------------------------------
# Strategy 1: apply the curated patch exactly.
# ---------------------------------------------------------------------------
$haveGit = [bool] (Get-Command git -ErrorAction SilentlyContinue)

if ($haveGit -and $patch -and (Test-Path -LiteralPath $patch -PathType Leaf)) {
    Push-Location -LiteralPath $src
    try {
        # `git apply --check` first, so a stale patch leaves no partial edits
        # behind. stderr is deliberately NOT captured: under PS 5.1 a native
        # command writing to stderr raises a terminating error whenever
        # $ErrorActionPreference is Stop.
        git apply --check $patch
        if ($LASTEXITCODE -eq 0) {
            git apply $patch
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[OK] applied TRAWL goto-timeout patch (git apply): $patch"
                exit 0
            }
            Write-Warning "git apply failed although --check passed, falling back to rule patch"
        }
        else {
            Write-Host "[INFO] patch does not match the current upstream code (upstream refactor), falling back to rule patch"
        }
    }
    finally {
        Pop-Location
    }
}
else {
    if (-not $haveGit) {
        Write-Host "[INFO] git not available, falling back to rule patch"
    }
    else {
        Write-Host "[INFO] patch file not found, falling back to rule patch"
    }
}

# ---------------------------------------------------------------------------
# Strategy 2: rule-based rewrite. Covers the old 3.ts/4.ts layout, the current
# browser.ts + metaRefresh.ts layout, and any future reshuffle.
# ---------------------------------------------------------------------------
$needle = "(?<!\d)$($LegacyMs)(?!\d)"
$replacement = "$($TimeoutMs)"

$changed = New-Object System.Collections.Generic.List[string]
foreach ($file in (Get-TierFiles -Base $src)) {
    # Detect a UTF-8 BOM up front so it survives the rewrite. The text is
    # split on "`n" only, so any trailing CR is re-emitted verbatim and
    # both LF and CRLF files keep their original line endings.
    $bytes = [IO.File]::ReadAllBytes($file.FullName)
    $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)

    $raw = [IO.File]::ReadAllText($file.FullName, [Text.Encoding]::UTF8)
    if ($hasBom) { $raw = [char]0xFEFF + $raw }

    $new = (($raw -split "`n") | ForEach-Object {
        if ($_ -match '^\s*timeout:' -and $_ -match 'Math\.min\(' -and $_ -match $needle) {
            $_ -replace $needle, $replacement
        }
        else {
            $_
        }
    }) -join "`n"

    if ($new -ne $raw) {
        [IO.File]::WriteAllText($file.FullName, $new, (New-Object System.Text.UTF8Encoding($hasBom)))
        $relative = $file.FullName.Substring($src.Length).TrimStart("\", "/")
        $changed.Add($relative)
    }
}

if ($changed.Count -gt 0) {
    Write-Host ("[OK] rule patch applied to {0} file(s), goto timeout {1} -> {2}:" -f $changed.Count, $LegacyMs, $TimeoutMs)
    foreach ($item in $changed) {
        Write-Host "       - $item"
    }
    exit 0
}

# Nothing left to rewrite. Either the patch is already in place (workflow
# re-run, or start-trawl.bat invoked twice) or upstream dropped the pattern
# entirely. Only the latter deserves a warning.
$already = 0
foreach ($file in (Get-TierFiles -Base $src)) {
    foreach ($line in ([IO.File]::ReadAllText($file.FullName, [Text.Encoding]::UTF8) -split "`n")) {
        if ($line -match '^\s*timeout:' -and $line -match 'Math\.min\(' -and $line -match "(?<!\d)$($TimeoutMs)(?!\d)") {
            $already++
        }
    }
}

if ($already -gt 0) {
    Write-Host "[OK] goto timeout already ${TimeoutMs} in $already place(s), nothing to do"
}
else {
    Write-Warning "rule patch matched nothing; TRAWL keeps the upstream ${LegacyMs}ms goto timeout"
}

exit 0
