# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# Copies the bridge macro into TBC's macro folder so it appears under the Macros tab.
# C:\ProgramData\Trimble\MacroCommands3 is read-only for normal users, so this asks for admin (UAC prompt).
# Install:   powershell -ExecutionPolicy Bypass -File install_macro.ps1
# Uninstall: powershell -ExecutionPolicy Bypass -File install_macro.ps1 -Uninstall
#
# Step 3 of README > How to install; shipped in the release zip. Run it from the unzipped folder (it finds the
# macro relative to its own location). Needs TBC installed; restart TBC afterwards so it picks up the macro.
# Re-run it only when a release changes the macro: the panel engine (mcp_server\ipy) is sent with every call
# and needs no reinstall.
#
# What it does:
#   install    creates C:\ProgramData\Trimble\MacroCommands3\MCP, copies tbc_macro\TbcMcpBridge.py into it,
#              creates an empty MCP.dict there and gives the local Users group Modify rights on that folder
#   uninstall  deletes the whole MCP folder (nothing else under MacroCommands3 is touched)
# How: when not already elevated, the script starts a second copy of itself as administrator (UAC prompt),
# waits for it and reports the result; the elevated copy does the actual work.
# Exit code: 0 on success, 1 when the UAC prompt was cancelled or the elevated copy failed (its exit code is
# passed on).
param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$dest = "C:\ProgramData\Trimble\MacroCommands3\MCP"
$src = Join-Path $PSScriptRoot "tbc_macro\TbcMcpBridge.py"

# is this process running with administrator rights (the elevated token)?
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    "Requesting administrator rights to write to $dest ..."
    # same script, same switch, in a new elevated powershell.exe; the path is quoted for folders with spaces
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
    if ($Uninstall) { $argList += '-Uninstall' }
    try {
        # -Verb RunAs shows the UAC prompt; -Wait -PassThru gives back the process to read its exit code
        $p = Start-Process powershell.exe -Verb RunAs -ArgumentList $argList -Wait -PassThru
    } catch {
        # Start-Process throws when the user answers No to the UAC prompt
        Write-Host "Cancelled - nothing was installed." -ForegroundColor Yellow
        exit 1
    }
    if ($p.ExitCode -ne 0) { Write-Host "Elevated install failed (exit $($p.ExitCode))." -ForegroundColor Red; exit $p.ExitCode }
    # success messages are printed here, in the user's own window (the elevated window closes when it is done)
    if ($Uninstall) { Write-Host "Removed $dest" -ForegroundColor Green }
    elseif (Test-Path (Join-Path $dest "TbcMcpBridge.py")) {
        Write-Host "Installed to $dest" -ForegroundColor Green
        "Restart TBC; the macro shows up as Macros > MCP > 'MCP Bridge'."
    }
    exit 0
}

# --- elevated part: does the actual install / uninstall (prints nothing on success) ---
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
        # *S-1-5-32-545 is the well-known SID of the local Users group (works on any Windows language);
        # (OI)(CI)M = Modify, inherited by files and subfolders; /T applies it to what is already there; /Q quiet.
        # icacls is a native program, so failure shows in $LASTEXITCODE rather than as an exception.
        & icacls $dest /grant "*S-1-5-32-545:(OI)(CI)M" /T /Q | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "icacls failed ($LASTEXITCODE)" }
    }
} catch {
    # keep the elevated window open so the error can be read before it closes
    Write-Host $_ -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}
