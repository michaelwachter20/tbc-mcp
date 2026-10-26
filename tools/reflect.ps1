# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# Read-only reflection over installed TBC assemblies.
# Usage: reflect.ps1 -Assembly Trimble.Sdk.Core -Type Trimble.Vce.Core.Components.Project [-Filter regex]
#        reflect.ps1 -Assembly Trimble.Sdk.Core -FindType regex
#
# Developer tool (not shipped in the release zip). Prints the public members of a type in one of TBC's .NET
# assemblies, or finds types by name, so bridge and IronPython code can be written against the real 2026.10
# API (the Macros SDK docs describe an older release). The README lists it as "type signatures from TBC's DLLs".
#
# Needs TBC: installed in C:\Program Files\Trimble\Trimble Business Center (not running). Read-only: assemblies
# are only loaded into this PowerShell process.
#
# How to run (Windows PowerShell):
#   powershell -ExecutionPolicy Bypass -File tools\reflect.ps1 -Assembly Trimble.Sdk.Core -Type Trimble.Vce.Core.Components.Project -Filter Serial
#   powershell -ExecutionPolicy Bypass -File tools\reflect.ps1 -Assembly Trimble.Sdk.Core -FindType Linestring
# -Assembly is the DLL's file name without .dll; -Filter is a regex on member names (default: everything).
#
# Output: "TYPE <full name> : <base type>", then one line per member: P property ({get} or {get;set}),
# M method with parameter types and names, F field, N nested type, E event. An enum prints its names and values.
param([string]$Assembly, [string]$Type, [string]$Filter = '.', [string]$FindType)
$tbc = "C:\Program Files\Trimble\Trimble Business Center"
# Dependencies of the loaded assembly are resolved from the TBC folder by this AssemblyResolve handler.
# $script:seen makes each name resolve at most once (a repeat request for the same name returns null);
# satellite .resources assemblies are ignored.
# A PowerShell scriptblock is fine here (run_ipy.ps1 needs compiled C# only because of IronPython's threads).
$script:seen = @{}
[AppDomain]::CurrentDomain.add_AssemblyResolve({
    param($s, $e)
    $n = (New-Object Reflection.AssemblyName($e.Name)).Name
    if ($n -like '*.resources' -or $script:seen.ContainsKey($n)) { return $null }
    $script:seen[$n] = 1
    $p = Join-Path $tbc "$n.dll"
    if (Test-Path $p) { return [Reflection.Assembly]::LoadFrom($p) }
    return $null
})
$asm = [Reflection.Assembly]::LoadFrom((Join-Path $tbc "$Assembly.dll"))
# All types of the assembly. GetTypes() throws ReflectionTypeLoadException when some types can't be loaded
# (a missing dependency); the exception still carries the ones that did load (nulls filtered out).
function Get-Types { try { $asm.GetTypes() } catch [Reflection.ReflectionTypeLoadException] { $_.Exception.Types | ? { $_ } } }
# -FindType: list the full names of matching types and stop
if ($FindType) { Get-Types | ? { $_.FullName -match $FindType } | % { $_.FullName }; return }
# throwOnError = $true: an unknown -Type stops the script with .NET's error
$t = $asm.GetType($Type, $true)
"TYPE $($t.FullName)  : $($t.BaseType)"
if ($t.IsEnum) { [Enum]::GetNames($t) | % { "  $_ = $([Convert]::ToInt64([Enum]::Parse($t, $_)))" }; return }
# Note: $bf is assigned twice and only the second value is used, so inherited public members are listed too
# (the DeclaredOnly/FlattenHierarchy variant on the first line has no effect).
$bf = [Reflection.BindingFlags]'Public,Instance,Static,DeclaredOnly,FlattenHierarchy'
$bf = [Reflection.BindingFlags]'Public,Instance,Static'
# property get/set accessors and other compiler-generated methods (IsSpecialName) are skipped
foreach ($m in $t.GetMembers($bf)) {
    if ($m.Name -notmatch $Filter) { continue }
    switch ($m.MemberType) {
        'Property' { "  P $($m.PropertyType.Name) $($m.Name)" + $(if ($m.CanWrite) { ' {get;set}' } else { ' {get}' }) }
        'Method' { if (-not $m.IsSpecialName) { $ps = ($m.GetParameters() | % { "$($_.ParameterType.Name) $($_.Name)" }) -join ', '; "  M $(if($m.IsStatic){'static '})$($m.ReturnType.Name) $($m.Name)($ps)" } }
        'Field' { "  F $(if($m.IsStatic){'static '})$($m.FieldType.Name) $($m.Name)" }
        'NestedType' { "  N $($m.FullName)" }
        'Event' { "  E $($m.Name)" }
    }
}
