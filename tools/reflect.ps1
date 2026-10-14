# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# Read-only reflection over installed TBC assemblies.
# Usage: reflect.ps1 -Assembly Trimble.Sdk.Core -Type Trimble.Vce.Core.Components.Project [-Filter regex]
#        reflect.ps1 -Assembly Trimble.Sdk.Core -FindType regex
param([string]$Assembly, [string]$Type, [string]$Filter = '.', [string]$FindType)
$tbc = "C:\Program Files\Trimble\Trimble Business Center"
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
function Get-Types { try { $asm.GetTypes() } catch [Reflection.ReflectionTypeLoadException] { $_.Exception.Types | ? { $_ } } }
if ($FindType) { Get-Types | ? { $_.FullName -match $FindType } | % { $_.FullName }; return }
$t = $asm.GetType($Type, $true)
"TYPE $($t.FullName)  : $($t.BaseType)"
if ($t.IsEnum) { [Enum]::GetNames($t) | % { "  $_ = $([Convert]::ToInt64([Enum]::Parse($t, $_)))" }; return }
$bf = [Reflection.BindingFlags]'Public,Instance,Static,DeclaredOnly,FlattenHierarchy'
$bf = [Reflection.BindingFlags]'Public,Instance,Static'
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
