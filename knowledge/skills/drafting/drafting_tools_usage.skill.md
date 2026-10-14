---
name: drafting_tools_usage
tbc_versions: ["2026.10"]
category: drafting
description: "Verified recipes for the Drafting tab: text, dimensions, labels, label tables, leader lines, blocks (create, insert, import, purge safely), hatch, quick profile, plotbox, plan/sheet sets, dynaview boundary sets, scale bars, 3D PDF. Includes where each result lives and how to clean it up."
requires_write: true
parameters: []
verified: "2026-10-14 on TBC 2026.10, throwaway objects on layer MCP_DRTEST, each result checked in the project (tests/drafting_tests.py)"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

> LICENSES DIFFER between users: check yours with `tbc_license`. The ANZ Toolbox drafting tools (Convert To MText,
> Explode Text, Find and Replace, Alignment/Excel/Legend tables, Slope Markers) were not licensed where this was written.

## Never

- **Never print.** Print Plan View / Print By Selection / Print Plan Set only print after Windows' Print dialog;
  don't press Print unless the user asks. Print Plan View's **Create** (plotbox) is safe.
- **Never fill personal details** (Create 3D PDF has name, phone, email, company, website boxes): leave them empty
  unless the user types them in chat.
- **Never press Apply in Purge Blocks without narrowing the list** (it purges every ticked unused block; see below).

## Entering values

- Coordinate boxes: point IDs work in WinForms boxes (Text insertion point, dimension points, label table location).
  Some WPF boxes do not resolve point IDs reliably (Print Plan View `Location`, Dynaview boundary `First sheet
  origin`, Scale Bar `Location`, Quick Profile From/To): type **"northing, easting"** there.
- Multi-select boxes ("Selected: N") take a list of serials. Dropdowns take the caption shown on screen.

## Recipes

| Tool | key | values / steps | result (where it lives) |
|---|---|---|---|
| Text | `createtext` | Layer, Height, Justification, `TextInsertionPointCoordinateEdit` = pt ID, `richTextBox1` = text; **Apply** | `ForeignCad.MText` on the layer (TextString) |
| Edit Text | `edittext` | select exactly ONE text first; the Create Text panel opens filled in; change `richTextBox1`; **Apply** | same MText updated (serial kept) |
| Linear Dimension | `createlineardimension` | "Two points" = true, `Point1CoordinateEdit` / `Point2CoordinateEdit` = pt IDs (labelled "Dimension style" on screen), `LocationPointCoordinateEdit` = where the dimension line goes, Layer; **Apply** | `ForeignCad.LinearDimension` + an MText for its text |
| Angular Dimension | `createangulardimension` | **needs picks in the Plan View**: linked by serial, both modes say "A valid segment cannot be obtained from the selected object." | ask the user to pick |
| Label Points | `labelpoints` | `Selection` = [point serials], Layer; **Add** | `ForeignCad.PointLabelEntity` per point ("Number of points labeled: N") |
| Label Lines | `labellines` | multi-select = [line serials], Layer; **Add** | `LineLabelEntity` per segment |
| Label Polygons | `labelpolygons` | multi-select = [polygon serials], Layer; **Add** | `PolygonLabelEntity` |
| Leader Lines | `createleaderlines` | `selTarget` = a label serial, `cdeInsertionPoint` = pt ID; **Apply** | `ForeignCad.Leader`, label moved to the insertion point |
| Point Label Table | `createpointlabeltable` | Layer, Title, `LocationCoordinateEdit` = pt ID; **OK** | `ForeignCad.PointLabelTable` on the layer |
| Line / Polygon Label Table | `createlinelabeltable` / `createpolygonlabeltable` | **label the lines/polygons first**; Layer, Title, Location; **OK** -> the **Edit Label Table** pane opens: `memberSelection` = [line/polygon serials], **Add** ("Number of segments/polygons: N"), Close | `LineLabelTable` / `PolygonLabelTable` - **not listed on a layer**: find by type/Title |
| Labeling Scale Factor | `planarscalefactor` | "Use a fixed scale factor" = true, `scaleFactorTextBox` = 1.0; **Apply** | project setting ("Labeling scale factor: 1.0000000000") |
| Create Block | `createblock` | `memberSelection1` = [objects], `BlockName`, `coordinateEdit1` = base point (pt ID); **Create** | definition = `Core.Components.BlockView` (not on a layer); source objects stay |
| Insert Block | `insertblock` | `blkComboBox1` = block name (the list shows only a sample of 700+ names; the fill searches all), `layer1`, `Location1` = pt ID, Rotation, Scale X/Y/Z; **Insert** | `ForeignCad.BlockReference` (BlockName) |
| Import Blocks | `importblocks` | `browseFile1` = folder with .dxf/.dwg; tick the FILE node under "My Block Files" in `treeView1` (TreeView node `Checked = True`); **Import** | one BlockView per block **plus one file-level block named after the file**. TBC remembers the folder: put it back afterwards. |
| Purge Blocks | `purgeblocks` | the list (`listView1`, checkboxes, 700+ entries) ticks EVERY unused definition. Untick all, tick only the ones to purge, check exactly those are ticked, **Apply**; reopen and confirm only those went | definitions removed (743 -> 742 for one test block). References must be deleted first. |
| Hatch | `createhatch` | `m_SelectedEntities` = [closed line serials], `m_oLayerControl`, `cb_Patterns` (SOLID, CROSS, ANGLE ...), `ne_Scale`; **Apply** | `ForeignCad.Hatch` |
| Quick Profile | `createquickprofile` | `createNew` (Define) = true, From / To = "N, E", surface `ComboBox` = surface name, `ClientAreaTextBox#4` = name, `ComboBox#5` = layer, `ClientAreaTextBox#5` = profile location "N, E"; **OK** | a drawn profile (Text + PolyLines) plus the quick profile object |
| Print Plan View (plotbox) | `printplanview` | Name, Scale, **Location = "N, E"** (sometimes pre-filled, sometimes '?': Create silently does nothing without it); **Create** only | `DynaviewBoundaryCollection` + `Boundary` + `PlanGridSheetSet` (+ BasicSheet, DynaViews), all named after the plotbox; deleting the first three removes all |
| Dynaview Boundary Set | `createdynaviewboundarycollection` | `txtName`, `lyrLayer`, `nudRows`, `nudColumns`, `crdOrigin` = "N, E", plot scale, paper size; **Apply** | `DynaviewBoundaryCollection` |
| Plan Set | `createplanset` | `NameTextBox`; **OK** | `PlanSet.PlanSetSheetView` |
| Sheet Set | `createsheetset` | `NameTextBox`, `cbSheetSetTypePicker` (Cross-Section, Custom, Profile, Standard), `cmbPaperSize`, Portrait/Landscape; **OK** | `PlanGridSheetSet` (for Standard) |
| Scale Bar | `createscalebar` | "Specify scale" = true, `nedScale`, `cboBarType` (Scale Line, Alternating Scale Bar, Double Alternating Scale Bar), `cboLayer`, `cdeLocation` = "N, E"; **OK** | `Alignment.ScaleBar` - **not listed on a layer** |
| Create 3D PDF | `create3dpdf` | `m_OutputFile` = full path (default is the project folder: choose one the user agrees to), `ModifyProjectSettings` = false, contact boxes empty; **OK** | the .pdf file (~11 MB for this project) |

## Not automatable without the view (ask the user)

- **Angular Dimension** (segment picks), **Insert Image** (file accepted and validated, corner typed, Apply creates
  nothing: it is placed and sized with grips in the view), **Copy to Sheet**, **Create Dynaview** and **Custom Sheet**
  (need a Sheet View / custom sheet set open), **Print By Selection** (window selection in the view).
- **Line Type Editor / Symbol Editor** open a separate program (PEDITOR.exe); close its window when done.

## Style managers (dialogs; documented, not changed)

Text Style, Dimension Style, Label Style, Label Table Style and Grid Style managers each have a style list plus
New / Delete / OK / Cancel; Line Style Manager and Symbol Manager copy styles from a source file (<< / < / X).
Opening Dimension Style Manager and cancelling still marks the project modified. Changing styles affects every
object that uses them: ask the user first.

## Cleaning up

Label tables, scale bars, plotboxes, plan/sheet sets and block definitions are **not on a layer**: deleting the
test layer's objects leaves them behind. Find them by type and name (walk the project) and delete with
`delete_entities`; purge test block definitions with the narrowed Purge Blocks procedure.
