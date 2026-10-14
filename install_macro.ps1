# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# Copies the bridge macro into TBC's macro folder so it appears under the Macros tab.
# C:\ProgramData\Trimble\MacroCommands3 is read-only for normal users, so this asks for admin (UAC prompt).
# Install:   powershell -ExecutionPolicy Bypass -File install_macro.ps1
# Uninstall: powershell -ExecutionPolicy Bypass -File install_macro.ps1 -Uninstall
param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$dest = "C:\ProgramData\Trimble\MacroCommands3\MCP"
$src = Join-Path $PSScriptRoot "tbc_macro\TbcMcpBridge.py"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    "Requesting administrator rights to write to $dest ..."
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
    if ($Uninstall) { $argList += '-Uninstall' }
    try {
        $p = Start-Process powershell.exe -Verb RunAs -ArgumentList $argList -Wait -PassThru
    } catch {
        Write-Host "Cancelled - nothing was installed." -ForegroundColor Yellow
        exit 1
    }
    if ($p.ExitCode -ne 0) { Write-Host "Elevated install failed (exit $($p.ExitCode))." -ForegroundColor Red; exit $p.ExitCode }
    if ($Uninstall) { Write-Host "Removed $dest" -ForegroundColor Green }
    elseif (Test-Path (Join-Path $dest "TbcMcpBridge.py")) {
        Write-Host "Installed to $dest" -ForegroundColor Green
        "Restart TBC; the macro shows up as Macros > MCP > 'MCP Bridge'."
    }
    exit 0
}

try {
    if ($Uninstall) {
        if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    } else {
        New-Item -ItemType Directory -Force $dest | Out-Null
        Copy-Item $src $dest -Force
        # TBC keeps a per-folder macro cache (MCP.dict) and must be able to write it as a normal user.
        # Grant Users modify on this MCP folder only (not the rest of MacroCommands3).
        $dict = Join-Path $dest "MCP.dict"
        if (-not (Test-Path $dict)) { New-Item -ItemType File $dict | Out-Null }
        & icacls $dest /grant "*S-1-5-32-545:(OI)(CI)M" /T /Q | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "icacls failed ($LASTEXITCODE)" }
    }
} catch {
    Write-Host $_ -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}
