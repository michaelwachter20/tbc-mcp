---
name: tbc_api_basics
tbc_versions: ["2026.10"]
category: basics
description: "Core facts for working with the TBC 2026 SDK from execute_python / saved scripts: units, coordinates, transactions, serials, layers, IronPython quirks."
requires_write: false
parameters: []
verified: "2026-10-13 on TBC 44.0 (2026.10)"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

## Key facts

- **Units:** model coordinates are stored in **meters**. `bridge.factor(prj)` = meters -> display units
  (`prj.Units.Linear.Convert(1.0, LinearType.Display)`); 3.280833333 for US survey feet.
- **Point3D:** `X = easting`, `Y = northing`, `Z = elevation`. `Point3D(x, y)` makes a 2D point (Z undefined/NaN).
- **Identity:** every object has a `SerialNumber` (UInt32). Look up with `prj.Concordance.Lookup(UInt32(serial))`
  or `bridge.lookup(prj, serial)`.
- **Containers:** `wv = prj[Project.FixedSerial.WorldView]` (serial 2) holds the model. Containers nest; walk with
  `bridge.walk(wv, graphical_only=True)`. Layers: `prj[Project.FixedSerial.LayerContainer]` (serial 6).
- **Active project:** `TrimbleOffice.TheOffice.CurrentProject.VceCoreProject`. Save: `TrimbleOffice.TheOffice.CurrentProject.Save()`.
- **Project names:** `prj.FileName` is the bare file name; `prj.ProjectName` is the full path (yes, reversed).
- **Changes need a transaction** (execute_python / write scripts do this for you):
  ```python
  prj.TransactionManager.AddBeginMark(Client.CommandGranularity.Command, "caption")
  with TransactMethodCall(prj.TransactionCollector) as guard:
      ...            # changes
      guard.Commit() # without this everything rolls back
  prj.TransactionManager.AddEndMark(Client.CommandGranularity.Command)
  ```
- **Selection:** `GlobalSelection.SelectedMembers(prj)`; set with `GlobalSelection.Items(prj).Set(List[UInt32](serials), True)`.
- **Commands:** `TrimbleOffice.TheOffice.CommandProcessor.CommandList` (~1180 keys), `ExecuteCommand(key, True, Array[Object]([]))`.
  Open panel: `TrimbleOffice.TheOffice.MainForm.CommandHost.TopCommand` (`.CommandUI` is the WinForms panel).
- **Ribbon:** `TrimbleOffice.TheOffice.MainForm.AppToolbar` (Infragistics UltraToolbarsManager). TBC saves ribbon
  appearance to `%APPDATA%\Trimble\Trimble Business Center\44.0\SurveyRibbon64.Layout` on exit.

## IronPython 3.4 quirks

- No f-strings; use `%` or `.format`.
- `typeof(T)` -> `clr.GetClrType(T)`.
- `out`/`ref` parameters: pass `clr.Reference[Point3D]()` and read `.Value`, e.g.
  `ref = clr.Reference[Point3D](); ok = surface.PickSurface(Point3D(x, y), ref)`.
- .NET UInt32 values are not Python ints: wrap with `int(...)` before JSON, `UInt32(n)` going in.
- Dicts parsed from JSON may not keep insertion order; pass ordered data as lists.
- Background threads must not touch the model; the bridge already runs everything on the UI thread.

## Gotchas

- The Macros SDK XML docs are v41 (TBC 2024); confirm members with `dir(obj)` or `obj.GetType().GetProperties()`.
- `Point.FeatureCode` is read-only on the point; set codes through the Create Point panel (see create_point_via_panel).

## Working rules

- Create geometry with verified tools (create_points, create_linestring) or TBC's own commands,
  not by adding raw CAD entity types (e.g. `ForeignCad.Poly3D`) through `wv.Add`.
- Delete with `delete_entities` (TBC's Delete command), not by removing objects from containers in code.
- Ask the user to save before experiments that change project-wide data.
