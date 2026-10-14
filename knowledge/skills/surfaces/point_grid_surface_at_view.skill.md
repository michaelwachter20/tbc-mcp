---
name: point_grid_surface_at_view
tbc_versions: ["2026.10"]
category: surfaces
description: "Make an N x M point grid where the user is looking (view center) and build a TBC surface from it with the Create Surface panel."
requires_write: true
parameters: [{"name": "nx", "type": "integer"}, {"name": "ny", "type": "integer"}, {"name": "spacing", "type": "number"}, {"name": "elevation", "type": "number"}]
verified: "2026-10-13: 20x20 @ 25 ft at view center -> 400 points, surface 'MCP Grid Demo' with 400 vertices / 722 triangles"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

## Steps

1. `tbc_view action=info` -> `center` (display units). "Where I'm looking" = the view center. If the user is zoomed
   far out, confirm the location (or show `tbc_view action=screenshot`).
2. Build the grid centred there: `x0 = cx - (nx-1)*spacing/2`, `y0 = cy - (ny-1)*spacing/2`; points
   `x0 + j*spacing, y0 + i*spacing`. Ask for elevations if not given (flat 0.0 was used in the demo).
3. `create_points` with all points in ONE call, on a layer such as `GRID`. Per the user's preference: **omit `name`**
   so points get the next free numeric IDs, and put the description in `feature_code` (e.g. `GRID`). With codes this
   goes through the Create Point panel (~1 s/point, ~7 min for 400); without codes it is one fast API call.
4. `set_selection serials=[...]` with the new point serials.
5. `command_ui_open key=surfacecreate` -> "Members to form surface" shows `Selected: N` (it takes the current
   selection). `command_ui_fill values=[["Name", "<surface name>"]] press=OK`. Optional fields: Color,
   Surface classification (Original, Design, As-built, ...).
6. Verify: `list_surfaces` (vertices = nx*ny, triangles = 2*(nx-1)*(ny-1) for a regular grid), clear the selection,
   `tbc_view action=set_extents` around the grid + `screenshot` to show the user.

## Gotchas

- The command key is `surfacecreate` (not createsurface).
- The surface stays linked to its points: raising a member point from 10 to 20 moved the surface at that point from 10 to 20 immediately (verified 2026-10-14).
- Surface `layer` is reported as null; surfaces are not on the points' layer.

