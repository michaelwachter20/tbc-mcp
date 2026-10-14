---
name: sample_surface
tbc_versions: ["2026.10"]
category: surfaces
description: "Get surface (TIN) elevations at XY locations, find surfaces, and iterate surface vertices."
requires_write: false
parameters: [{"name": "surface", "type": "string", "required": true, "description": "surface name or serial"}]
verified: "2026-10-13 on a large production surface (510,991 vertices) - sampled z matched vertex z exactly"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

## Tool form

- `list_surfaces` -> name, serial, vertex/triangle counts, elevation range.
- `surface_elevation surface=<name> points=[{"x": easting, "y": northing}]` -> `z` or `on_surface: false` outside.

## Code template

```python
s = bridge.lookup(prj, 111986)          # or find by name in bridge.walk(wv, False)
f = bridge.factor(prj)
ref = clr.Reference[Point3D]()
ok = s.PickSurface(Point3D(x / f, y / f), ref)   # meters in
z = ref.Value.Z * f if ok else None              # display out

# vertices (skip deleted ones)
for i in range(s.NumberOfVertices):
    if s.IsVertexPresent(i):
        p = s.GetVertexPoint(i)
```

## Gotchas

- Surfaces are `Trimble.Vce.Gem.Model3D`. Layers named "SURF" may only hold CAD Poly3D/MText, not TINs.
- Large surfaces (500k+ vertices): avoid returning all vertices; aggregate inside the script.
