# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# Build the release zip locally (the same package GitHub builds when a version tag is pushed).
# Usage: powershell -ExecutionPolicy Bypass -File tools\make_release.ps1 [-Version 0.3.0]
# Output: dist\tbc-mcp-v<version>.zip  (version defaults to SERVER_VERSION in mcp_server\tbc_mcp_server.py)
#
# Maintainer tool (not shipped). Mirrors .github\workflows\release.yml so the package can be checked before a
# tag is pushed: stage the paths listed in release_files.txt into dist\tbc-mcp-v<version>\, strip per-machine
# and generated files, zip the staging folder (the zip holds one top-level folder tbc-mcp-v<version>), then
# delete the staging folder. Needs no TBC. dist\ is in .gitignore. Pass -Version without the leading "v".
# Any error stops the script ($ErrorActionPreference = 'Stop').
param([string]$Version)
$ErrorActionPreference = 'Stop'
# repository root = the parent of this tools\ folder
$root = Split-Path -Parent $PSScriptRoot
# read the version from the line SERVER_VERSION = "x.y.z" (regex group 1)
if (-not $Version) {
    $m = Select-String -Path (Join-Path $root 'mcp_server\tbc_mcp_server.py') -Pattern 'SERVER_VERSION = "([^"]+)"'
    $Version = $m.Matches[0].Groups[1].Value
}
$name = "tbc-mcp-v$Version"
$dist = Join-Path $root 'dist'
$stage = Join-Path $dist $name
# start from an empty staging folder
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force $stage | Out-Null

# release_files.txt: one repo-relative path per line, blank lines and # comments skipped; folders copied whole
$items = Get-Content (Join-Path $root 'release_files.txt') | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith('#') }
foreach ($i in $items) { Copy-Item (Join-Path $root $i.Trim()) $stage -Recurse -Force }

# never ship per-machine or generated files
Get-ChildItem $stage -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
Get-ChildItem $stage -Recurse -File -Include '*.pyc', 'crash_log.md', 'tbc_errors.log', '*.tmp' | Remove-Item -Force
# an old-style license profile folder inside knowledge\ (profiles now live in %LOCALAPPDATA%\TBC-MCP)
$lic = Join-Path $stage 'knowledge\license'
if (Test-Path $lic) { Remove-Item -Recurse -Force $lic }

$zip = Join-Path $dist "$name.zip"
# Compress-Archive won't overwrite an existing zip, so remove it first
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path $stage -DestinationPath $zip
# count the files before the staging folder is deleted, for the summary line
$n = (Get-ChildItem $stage -Recurse -File).Count
Remove-Item -Recurse -Force $stage
"Built $zip ($n files, {0:N0} KB)" -f ((Get-Item $zip).Length / 1KB)
