---
name: create_points_api
tbc_versions: ["2026.10"]
category: points
description: "Create many points quickly through the SDK (create_points tool or Point.CreatePoint in a script)."
requires_write: true
parameters: [{"name": "points", "type": "array", "required": true, "description": "name, easting, northing, elevation?, layer?"}]
verified: "2026-10-13 - 3D and 2D points created, read back exactly, deleted"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

## When to use

Bulk point creation without feature codes. One call = one undo step.

## Tool form

`create_points points=[{"name": "P1", "easting": 20500, "northing": 10500, "elevation": 6.5, "layer": "Points"}]`
(display units by default; omit `elevation` for 2D; the layer is created if missing).

## Code template (execute_python / saved script)

```python
f = bridge.factor(prj)                       # meters -> display
pt = TbcPoint.CreatePoint(prj, "P1")
pt.AddPosition(Point3D(20500 / f, 10500 / f, 6.5 / f))   # model units are meters
pt.Layer = Layer.FindOrCreateLayer(prj, "Points").SerialNumber
result = int(pt.SerialNumber)
```

## Gotchas

- Feature codes cannot be set this way (`Point.FeatureCode` is read-only) - use create_point_via_panel.
- Duplicate names are allowed silently via the API (no popup), unlike the Create Point panel.
