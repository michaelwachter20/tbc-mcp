---
name: create_point_via_panel
tbc_versions: ["2026.10"]
category: points
description: "Create office-entered points through TBC's Create Point panel (addpoint), including feature codes and layer."
requires_write: true
parameters: [{"name": "points", "type": "array", "required": true, "description": "point id, northing, easting, elevation, feature code, layer"}]
verified: "2026-10-13 - MCPUI2/MCPUI3 created with exact coordinates and feature code TEST"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

## When to use

When points need a **feature code** (the API tool create_points cannot set codes) or TBC's normal point-creation
behaviour. For plain points without codes, `create_points` is quicker.

## Steps

1. `command_ui_open key=addpoint`
2. For each point:
   ```json
   {"values": [["Point ID", "1001"], ["Feature code", "EP"], ["Layer", "Points"],
               ["Northing", "10520"], ["Easting", "20520"], ["Elevation", "6.75"]],
    "press": "Add"}
   ```
   with `command_ui_fill`. The panel stays open; TBC auto-increments the Point ID afterwards.
3. `command_ui_close`, then verify with `list_points name_contains=...` (feature_code is returned).

## Fields (Create Point, TBC 2026)

| label | id | notes |
|---|---|---|
| Point ID | m_tbPointID | auto-increments after Add |
| Feature code | m_tbFieldCode | FeatureCodesEdit; any text accepted |
| Layer | m_Layer | dropdown of existing layer names only |
| Northing / Easting | m_tbPlanar1 / m_tbPlanar2 | display units; shown as `10520.000` |
| Elevation | m_tbHeight1 | display units; leave unset for 2D |
| Status | m_cbStatus | Enabled / Enabled as check / Disabled |
| Coordinate type | m_cbCoordSystem | Grid (default) / Local / Global |
| Measure Codes mode | MeasureCodesCheckBox | leave off |

Buttons: **Add** (id `Ok`), **Close** (id `Cancel`).

## Gotchas

- Duplicate Point ID -> popup "Point ID "X" already exists ... Do you still want to continue?" (Yes/No).
  Answer with `tbc_dialogs action=click button=No` unless duplicates are wanted.
- Layer must already exist (create it first with `create_layer`).
