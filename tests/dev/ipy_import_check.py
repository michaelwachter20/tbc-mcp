# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Check that every TBC type the bridge uses resolves against the installed TBC DLLs.
Run with: powershell -File run_ipy.ps1 ipy_import_check.py

One-off development probe. Loads tbc_macro\\TbcMcpBridge.py under TBC's IronPython (outside TBC) and reports
whether its SDK imports resolved, then checks that the SDK types it relies on still have the members it calls.
Useful after a TBC update: a missing member here means the bridge needs new handling for that release.

Needs TBC
    No running TBC, but the TBC install (IronPython 3.4 and the Trimble SDK DLLs).

How to run (from tests\\dev)
    powershell -ExecutionPolicy Bypass -File run_ipy.ps1 ipy_import_check.py

Output / pass
    Console only, read by eye: IN_TBC True and "import errors: none", then "missing: none" for each type.
"""
import sys, os
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "..", "tbc_macro"))
import TbcMcpBridge as B
# IN_TBC is the bridge's flag that its core TBC imports succeeded; _IMPORT_ERRORS lists any that failed
print("IN_TBC (core imports ok):", B.IN_TBC)
print("import errors:", B._IMPORT_ERRORS or "none")
for n in ("TbcPoint", "Model3D", "_ls", "TrimbleOffice"):
    print(" ", n, "->", getattr(B, n))
import clr
# (type, members the bridge uses on it); a type that failed to import (None) is skipped
for t, members in ((B.TbcPoint, ("CreatePoint", "GetAllPoints", "AddPosition", "Position", "Layer", "FeatureCode")),
                   (B.Model3D, ("PickSurface", "NumberOfVertices", "NumberOfTrianglesWithMaterial", "MinElevation", "Name")),
                   (B.Layer, ("FindOrCreateLayer", "DefaultColor", "Visible", "Locked", "Members")),
                   (B.GlobalSelection, ("SelectedMembers", "Items")),
                   (B.Project, ("FixedSerial", "Units", "TransactionManager", "TransactionCollector", "Concordance", "Modified"))):  # TrimbleOffice.TheOffice only exists inside a running TBC
    if t is None:
        continue
    missing = [m for m in members if not hasattr(t, m)]
    print(" ", t, "missing:", missing or "none")
# _ls: the bridge's tuple of linestring types (Linestring first); report which closed/element APIs it has
if B._ls:
    L = B._ls[0]
    print("  Linestring closed attr:", [a for a in ("IsClosed", "Closed") if hasattr(L, a)],
          "AppendElement:", hasattr(L, "AppendElement"), "ElementAt:", hasattr(L, "ElementAt"))
print("  FixedSerial.WorldView =", B.Project.FixedSerial.WorldView, " LayerContainer =", B.Project.FixedSerial.LayerContainer)
print("  Client.CommandGranularity.Command =", B.Client.CommandGranularity.Command)

