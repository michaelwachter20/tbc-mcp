# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# Host TBC's IronPython 3.4 engine (read-only use of the TBC install) and run a script.
# Usage: run_ipy.ps1 <script.py> [args...]
#
# One-off development tool (tests\dev). Runs a Python script under TBC's own IronPython 3.4 engine, loaded
# from the TBC install folder, without starting TBC. The ipy_*.py probes in this folder use it to load the
# bridge macro (tbc_macro\TbcMcpBridge.py) and the Trimble SDK DLLs outside TBC.
#
# Needs TBC: installed (C:\Program Files\Trimble\Trimble Business Center), not running. Nothing in the
# install is changed.
#
# How to run (Windows PowerShell):
#   powershell -ExecutionPolicy Bypass -File tests\dev\run_ipy.ps1 tests\dev\ipy_import_check.py
#   powershell -ExecutionPolicy Bypass -File tests\dev\run_ipy.ps1 tests\dev\ipy_bridge_harness.py C:\Temp\info.json 120
#
# What the script sees: sys.argv = [full path of the script, args...] (blank args dropped); module search
# path = TBC's IronPython 3.4 Lib folder + the script's own folder.
#
# Output / exit code: whatever the script prints; on an exception, one line "<ExceptionType>: <message>" on
# stderr (the inner exception when there is one) and exit code 1.
#
# -Script is the .py file to run; every remaining argument is collected into -ScriptArgs.
param([Parameter(Mandatory)][string]$Script, [Parameter(ValueFromRemainingArguments)][string[]]$ScriptArgs)
$tbc = "C:\Program Files\Trimble\Trimble Business Center"
# Resolver must be compiled C#: PowerShell scriptblocks crash when invoked on IronPython's threads.
# The class hooks AppDomain.AssemblyResolve: whenever .NET can't find an assembly (IronPython's own DLLs, the
# Trimble SDK assemblies the bridge imports), it is loaded from the TBC folder if <name>.dll exists there.
# Satellite ".resources" assemblies are left to the default lookup (null = not found).
Add-Type -TypeDefinition @"
using System; using System.IO; using System.Reflection;
public static class TbcResolver {
    static string dir;
    public static void Install(string d) { dir = d; AppDomain.CurrentDomain.AssemblyResolve += Resolve; }
    static Assembly Resolve(object s, ResolveEventArgs e) {
        string n = new AssemblyName(e.Name).Name;
        if (n.EndsWith(".resources")) return null;
        string p = Path.Combine(dir, n + ".dll");
        return File.Exists(p) ? Assembly.LoadFrom(p) : null;
    }
}
"@
[TbcResolver]::Install($tbc)
# load the IronPython engine shipped with TBC (the same version the bridge runs on inside TBC)
[void][Reflection.Assembly]::LoadFrom("$tbc\IronPython.dll")
[void][Reflection.Assembly]::LoadFrom("$tbc\IronPython.Modules.dll")
$engine = [IronPython.Hosting.Python]::CreateEngine()
# module search path: TBC's IronPython standard library + the script's folder (so it can import its neighbours)
$paths = New-Object 'System.Collections.Generic.List[string]'
$paths.Add("$tbc\IronPython 3.4\Lib"); $paths.Add((Split-Path -Parent (Resolve-Path $Script)))
$engine.SetSearchPaths($paths)
# Hand sys.argv to the engine as JSON through an environment variable, which avoids quoting the arguments
# into Python source. Where-Object { $_ } drops empty arguments.
[string[]]$all = @([string](Resolve-Path $Script)) + @($ScriptArgs | Where-Object { $_ })
$env:TBC_IPY_ARGV = ConvertTo-Json -Compress -InputObject $all
[void]$engine.Execute("import sys, json; from System import Environment; sys.argv = json.loads(Environment.GetEnvironmentVariable('TBC_IPY_ARGV'))")
try {
    # run the script file in a fresh scope; its return value is discarded
    $engine.CreateScriptSourceFromFile([string](Resolve-Path $Script)).Execute($engine.CreateScope()) | Out-Null
} catch {
    # PowerShell wraps .NET exceptions from method calls; the InnerException is the Python error itself
    $ie = $_.Exception.InnerException
    if (-not $ie) { $ie = $_.Exception }
    [Console]::Error.WriteLine($ie.GetType().FullName + ": " + $ie.Message)
    exit 1
}

