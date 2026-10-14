---
name: linework_tools_usage
tbc_versions: ["2026.10"]
category: linework
description: "Verified recipes for every licensed Linework tab tool (create, edit, advanced): exact fields, how to enter points and objects, results and gotchas. Capture Outline and Fillet/Chamfer need picks in the Plan View."
requires_write: true
parameters: []
verified: "2026-10-13 on TBC 2026.10, throwaway objects on layer MCP_LWTEST, each result checked numerically (tests/linework_tests.py, 29 automated tests)"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

> LICENSES DIFFER between users: check your own with `tbc_license`. ANZ Toolbox tools (Reverse, Chord, Merge,
> Best Fit Circle, Simplify ...) were not licensed on the machine where this was written.

## Entering values (command_ui_fill does this for you)

| Box | What to pass | How the tool enters it |
|---|---|---|
| Coordinate box, WinForms (Three-Point Circle/Rectangle, Boundary, Polyline) | point ID string, e.g. `"4700486"` | real keystrokes + Enter (setting it in code shows the value but TBC says "Pick a point in a Plan View") |
| Coordinate box, WPF (Create Circle, Arc, Rectangle, Quick Line, Divide Area) | point ID string | typed, committed by tabbing out; a value ending in `\n` presses Enter once instead |
| Object picker, WinForms (`Line`, `Line to offset`, `Base line` ...) | integer serial | `SetEntity` |
| Object picker, WPF (Divide Area `Area to Divide`, Insert Segment `Line`) | integer serial | `SetEntity` on the WPF SelectEntity |
| Multi-select box ("Selected: N") | list of serials, e.g. `[123, 456]` | `MemberSelection.SetSelection` (needed when a panel has two, or ignores the preselection) |
| Side to offset | `"Left"` / `"Right"` | sets the `Side` enum (typed text alone stayed Right) |

- Reference locations are **numeric point IDs** (the user's ID rule).
- Lines built from points take the point elevations unless the panel has its own Elevation box.

## Create

| Tool | key | values / steps | result |
|---|---|---|---|
| Polyline | `createpolyline` | Name, Layer, Elevation, "Specify individual points" = true; per vertex `Next point` = pt ID + press **Add Point**; **Close** | `ForeignCad.PolyLine`, z = Elevation |
| Linestring | `createlinestring` | Name, Layer, **OK** -> Edit Linestring pane (below) | `Alignment.Linestring.Linestring`, vertices linked to the points |
| Polygon | `createpolygon` | as Linestring | `Alignment.Linestring.Polygon`, closed automatically |
| Breakline | `createbreakline` | Name, Layer, "Add to surface" = surface name, **OK** -> Edit Linestring pane | linestring that is a member of the surface (surface recomputes: use a small surface for tests) |
| Boundary | `createboundary` | "Polygon (from a line)" = true, `m_ctrlExistingEntity` = closed line serial, Name, Layer, **OK** | `Data.Construction.Boundary` with the line's corners. Polygon mode with typed IDs keeps only the first and last point. |
| Circle | `createcircle` | Name, Layer, Elevation, Center point = pt ID, Radius; **Create** | `ForeignCad.Circle` |
| Three-Point Circle | `createthreepointcircle` | Point one/two/three = pt IDs; **Apply** | circle through the 3 points |
| Arc | `createarc` | "Create arc using" (Start, Middle, End / Start, Center, End / Center, Start, Angle / Start, End, Angle / Start, End, Radius) + matching boxes; **Apply** | `ForeignCad.Arc` (may be stored end->start) |
| Rectangle | `createrectangle` | Corner one, Corner two (opposite); **OK** | closed `ForeignCad.PolyLine` |
| Three-Point Rectangle | `createthreepointrectangle` | Corner one, Corner two (one side), Width; **Apply** | closed polyline, width to the right of one->two |
| Best-Fit Line | `bestfitline` | select the points first; Line type (Straight Line 2D/3D, Polynomial Curve 2D/3D + degree), Layer; **OK** | linestring through the points (2D: no z) |
| Quick Line | `quickline` | Name, Layer; per vertex `Coordinate` = `"<pt ID>\n"` (Enter adds the vertex); **Apply** | linestring through the points |
| Convert To Linestring | `anz_converttolinestring` | select CAD lines/polylines first; **OK** | linestring; the source CAD polyline is **replaced** (gone afterwards) |
| Capture Outline | `captureoutline` | **needs picks in the Plan View** (2 per edge). Typed coordinates replace each other; Enter in Coordinate means OK and gives "Enter at least two coordinates." | ask the user to pick |

### Edit Linestring pane (Linestring, Polygon, Breakline)

`LocationTypeComboBox` = "Point ID"; then per vertex fill `Point ID` and click **Save** as a separate call (pressing
Save in the same fill lost vertices). Segment type (`SegmentTypeComboBox`): Straight, Smooth curve, Best fit arc, Arc,
Tangent arc, Deflection, PI Arc, Offset. **Close** finishes; a line closed with fewer than 2 vertices is discarded.

## Edit

| Tool | key | values / steps | result |
|---|---|---|---|
| Offset | `offsetlinestring` | Line to offset = serial, Offset distance, Side to offset = Left/Right (relative to line direction), Name, Layer; **Apply** | new linestring (eastward line, Left 10 -> +10 N; no z) |
| Trim/Extend | `trimextendlines` | "Multiple lines to bounding lines" = true, `memBoundariesMulti` = [bounding], `MultipleMemberSelection` = [lines], Extend or Trim radio; **Apply** | lines trimmed/extended to the bounding lines. "One line to bounding lines" needs a view pick. |
| Divide Lines | `divideline` | select the line(s) first; "Divide by number of separated objects" = true, `numUpDownDivideNum` = n (or Divide by length + `dedDivideLength`); **Apply** | n lines (100 ft into 4 -> 4 x 25) |
| Break | `breakline` | Line = serial, Distance along; **Break** | two lines (0-40, 40-100) |
| Explode Lines | `anz_explodelines` | select the line first; "Every segment" (or "Large deflections" + Max angle); **Apply** | one line per segment; the original is removed |
| Join | `joinlines` | "Two lines" = true, `TwoPrimarySelectEntity` = base, `TwoSecondarySelectEntity` = other; **Join** | one line (the base line keeps its serial) |
| Clip | `cliplines` | "Remove lines outside bounding lines" (or inside / break at crossings), `lineSelection` = [lines], `clippingBoundariesSelection` = [closed lines]; **Apply** | pieces outside removed |
| Insert Segment | `standardinsertlinesegment` | select the line first (or Line = serial), Location = pt ID; **Insert** | vertex inserted in the nearest segment |
| Delete Segment | `deletelinesegment` | Line = serial; pick an item in the segment list (e.g. "1 - Straight - Point ID"); **Delete** | that segment removed |
| Set Line Elevation | `setlineelevation` | Line = serial, Elevation; **Apply** | constant elevation. **2D lines only**: lines with vertex z give "Linestrings with 3D coordinates cannot be given a constant elevation." |
| Append Tracked | `appendtrackedline` | Base line = serial, Line to append = serial; **Append** | base line extended through the appended line's vertices |
| Fillet/Chamfer | `filletchamfer` | **needs picks in the Plan View** (the pick location chooses the segments). Linked by serial only: Apply does nothing, or TBC asks to accept a 0.000 radius (answer **No**). | ask the user to pick |

## Advanced

| Tool | key | values / steps | result |
|---|---|---|---|
| Divide Area | `dividearea` | **first** `Area to Divide` = polygon serial and check it shows "Polygon : name"; then Divide area based on (Number of subareas / Target area / Distance from Baseline), Amount, Origin + End point = pt IDs (the baseline); **Divide** | new polygons (100x50, baseline A-B, 2 -> two 100x25 halves parallel to the baseline; the original polygon remains). The fill tool refuses Origin/End point while the area is empty. |
| Composite Geometry | `createcompositegeometry` | Name, Layer, Composite type (polyline/polygon), "Elements to add to composite" = [serials], **Add**, **Ok** | `CompositePolyLine` through the elements |
| Track Region | `trackregionoutline` | Name, Layer, `m_LinesSelection` = [lines forming a closed region], Reference point = pt ID inside; **Apply** | linestring around the region |
| Detect Crossing Geometry | `crossinggeometry` | `memberSelection1` = [lines] ("Suitable for calculation: N"), optional Vertical tolerance; **Apply**; read the results with `ui_grid action=read` (Higher/Lower geometry, Easting, Northing, Vertical difference); **Remove All Flags** to clean up | one row per crossing; orange flags on the higher line. **Report** opens a report: not needed. |
| Integrate to Geometry | `geometrypointintegratecmd` | select a CLOSED linestring/polygon first; Starting point ID (next free number); **Process** | one point per vertex on the default Points layer, numbered clockwise, skipping existing IDs (verified in the Survey tab tests) |

## Status

29 of the 31 licensed Linework tools are verified by automated tests. Capture Outline and Fillet/Chamfer need the
user to pick in the Plan View.
