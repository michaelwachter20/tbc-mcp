---
name: cad_editing_tools
tbc_versions: ["2026.10"]
category: cad
description: "Verified recipes for the CAD tab editing tools: Move, Rotate, Scale, Mirror, Copy Objects, Change Elevation, Relayer, Name Objects, Explode, Create Points at Intervals, Drape on Surface (fields, values, results, gotchas)."
requires_write: true
parameters: []
verified: "2026-10-13 on TBC 2026.10, throwaway objects on layer MCP_CADTEST, each result checked numerically (tests/cad_edit_tests.py)"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

> LICENSES DIFFER between users: license notes here (e.g. 'not licensed', ANZ tools) describe the machine where this was written. Check your own with `tbc_license` - search results flag commands your license lacks.
## General pattern

1. Select the objects first: `set_selection serials=[...]`. Panels with an "Objects to ..." field
   (`SelectedEntities`, a MemberSelection) take the current selection and show `Selected: N`.
2. `command_ui_open key=<key>` (license check + pacing + waits for the panel to finish loading).
3. `command_ui_fill values=[...] press=Apply`. Coordinate boxes (From / To / Around) accept a **point ID**
   (numeric, per the user's ID rule), which avoids any northing/easting ambiguity.
4. Verify with read tools, then `command_ui_close` and `set_selection serials=[]`.

## Recipes

| Tool | key | values (in order) | result |
|---|---|---|---|
| Move | `moveobjects` | From = pt ID, To = pt ID | objects shifted by To - From |
| Rotate | `rotateobjects` | Around = pt ID, Angle = "90" | **positive angle = clockwise** |
| Scale | `scaleobjects` | From = pt ID, "Horizontal (X) scale" = 2 | X and Y scaled (Lock X and Y on by default) |
| Mirror | `mirrorobjects` | From = pt ID, To = pt ID | mirrored **copy**; source kept unless "Delete source objects" |
| Copy Objects | `copyobjects` | ("Relayer copied objects" = false) | copy created in place, same layer |
| Change Elevation | `changeelevation` | "Absolute elevation" = true, `m_NewElevation` = "12.5" | see gotcha: stored as a vertical element on linestrings |
| Relayer Objects | `relayerobjects` | "Target layer" = layer name | layer changed (WPF panel; buttons Apply/Close/Options) |
| Name Objects | `nameobjects` | "Object to name" = serial, "New name" = text | renamed (picker field: pass the serial) |
| Explode | `explode` | (press **Explode**) | **blocks only** (BlockReference -> CAD Lines); polylines/linestrings: "No explodable objects are selected." |
| Create at Intervals | `createatinterval` | "Selection" = true, Interval, "Starting point ID", Layer | 200 ft line @ 25 ft -> 9 points |
| Drape on Surface | `drapeobjectsonsurface` | Surface = surface serial, `ReferenceLineSelectEntity` = line serial, Layer = output layer | **new** `DrapedLine` object on the chosen Layer, sitting on the surface |

## Gotchas

- **Ambiguous labels**: Change Elevation has two "Elevation" fields (use id `m_NewElevation`); Drape has two
  "Reference line/point" fields (use id `ReferenceLineSelectEntity`). The fill tool refuses to guess and lists ids.
- **Change Elevation on a linestring** clears vertex z and adds a vertical element at the new elevation.
  `get_entity` reports the effective elevation (`z_source: vertical profile`).
- **Drape** does not modify the source line; it creates a `Trimble.Vce.Alignment.DrapedLine` (read its geometry
  with `ComputePolySeg().ToPoint3DArray()`). Set the Layer field or it goes to the panel's default layer.
- **Numeric boxes** (e.g. Scale factors, NumericEdit) are set through their Value; typed text is ignored. The fill
  tool handles this.
- **Radio buttons / checkboxes** are clicked like a user; setting them in code can leave the command's mode stale.
- To get explodable test data safely, copy an existing block with Copy Objects and relayer the copy; create test objects with TBC commands rather than raw API calls.
