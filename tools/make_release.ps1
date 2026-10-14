# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# Build the release zip locally (the same package GitHub builds when a version tag is pushed).
# Usage: powershell -ExecutionPolicy Bypass -File tools\make_release.ps1 [-Version 0.3.0]
# Output: dist\tbc-mcp-v<version>.zip  (version defaults to SERVER_VERSION in mcp_server\tbc_mcp_server.py)
param([string]$Version)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Version) {
    $m = Select-String -Path (Join-Path $root 'mcp_server\tbc_mcp_server.py') -Pattern 'SERVER_VERSION = "([^"]+)"'
    $Version = $m.Matches[0].Groups[1].Value
}
$name = "tbc-mcp-v$Version"
$dist = Join-Path $root 'dist'
$stage = Join-Path $dist $name
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force $stage | Out-Null

$items = Get-Content (Join-Path $root 'release_files.txt') | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith('#') }
foreach ($i in $items) { Copy-Item (Join-Path $root $i.Trim()) $stage -Recurse -Force }

# never ship per-machine or generated files
Get-ChildItem $stage -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
Get-ChildItem $stage -Recurse -File -Include '*.pyc', 'crash_log.md', 'tbc_errors.log', '*.tmp' | Remove-Item -Force
$lic = Join-Path $stage 'knowledge\license'
if (Test-Path $lic) { Remove-Item -Recurse -Force $lic }

$zip = Join-Path $dist "$name.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path $stage -DestinationPath $zip
$n = (Get-ChildItem $stage -Recurse -File).Count
Remove-Item -Recurse -Force $stage
"Built $zip ($n files, {0:N0} KB)" -f ((Get-Item $zip).Length / 1KB)
