# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# Host TBC's IronPython 3.4 engine (read-only use of the TBC install) and run a script.
# Usage: run_ipy.ps1 <script.py> [args...]
param([Parameter(Mandatory)][string]$Script, [Parameter(ValueFromRemainingArguments)][string[]]$ScriptArgs)
$tbc = "C:\Program Files\Trimble\Trimble Business Center"
# Resolver must be compiled C#: PowerShell scriptblocks crash when invoked on IronPython's threads.
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
[void][Reflection.Assembly]::LoadFrom("$tbc\IronPython.dll")
[void][Reflection.Assembly]::LoadFrom("$tbc\IronPython.Modules.dll")
$engine = [IronPython.Hosting.Python]::CreateEngine()
$paths = New-Object 'System.Collections.Generic.List[string]'
$paths.Add("$tbc\IronPython 3.4\Lib"); $paths.Add((Split-Path -Parent (Resolve-Path $Script)))
$engine.SetSearchPaths($paths)
[string[]]$all = @([string](Resolve-Path $Script)) + @($ScriptArgs | Where-Object { $_ })
$env:TBC_IPY_ARGV = ConvertTo-Json -Compress -InputObject $all
[void]$engine.Execute("import sys, json; from System import Environment; sys.argv = json.loads(Environment.GetEnvironmentVariable('TBC_IPY_ARGV'))")
try {
    $engine.CreateScriptSourceFromFile([string](Resolve-Path $Script)).Execute($engine.CreateScope()) | Out-Null
} catch {
    $ie = $_.Exception.InnerException
    if (-not $ie) { $ie = $_.Exception }
    [Console]::Error.WriteLine($ie.GetType().FullName + ": " + $ie.Message)
    exit 1
}

