---
name: selection_tools
category: home
description: "Verified recipes for the Home tab Selection group (Select Points, Duplicate Points, Elevation, Observations, Layer, Polygon, Similar, Advanced/Quick Select, Invert, Select All) and how to combine them for complex selections."
requires_write: false
parameters: []
tbc_versions: ["2026.10"]
updated: 2026-10-14T10:35:32
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.
Selection commands only change what is selected - safe to use. Read the result with `get_selection` (serials).
Combine them for complex selections: most panels have **Add to current selection** (`chkAddToCurrentSelection` /
`m_AddToSelectionCheckbox`), and `set_selection` / Invert / Select All work on whatever is selected.

## Recipes (verified, tests/selection_tests.py)

| Tool | key | values / steps | result |
|---|---|---|---|
| Select Points | `selectpoints` | `cboLayer` = layer (or `<<All Layers>>`), `txtFieldCode` = code, `SelectedPointID` = pt ID, `ObservedFromPointID`, quality checkbox lists (`clbHorizontalQuality` / `clbElevationQuality` / `clbHeightQuality`: Fixed in Adjustment, Adjusted, Control, Survey, Mapping, Unknown), `cbFeatureStatus` (Locked Yes/No), attribute name/value; **OK** | points matching ALL given criteria |
| Add to selection | (any panel) | `chkAddToCurrentSelection` = true | keeps the current selection and adds the matches (verified: {B} + code SELA -> {A, B, C}) |
| Select Duplicate Points | `selectduplicatepoints` | `MinimumDistance` (display units); Identical / Ignored / Different (how codes etc. are compared); **OK** | every point within the distance of another point, **whole project** |
| Select by Elevation | `selectbyelevation` | `m_MinElevationValue`, `m_MaxElevationValue`, "Entirely" or "Partially within range"; **OK** | all objects in the range, **whole project** (1,284 here for 15-25) |
| Select Observations | `selectobservations` | `clbType` checkbox list (Mean Angle, RTK Vector, Total Station Observation), `clbStatus` (Disabled, Enabled, Enabled as check), From/To point IDs, observation ID, start/end time, duration; **OK** | observations |
| Select by Layer | `selectbylayer` | tick layers in `LayerCheckedListBox` (fill with a layer name or a list; `{"only": [...]}` unticks the rest) - selection updates as you tick; **Close** | everything on those layers |
| Select by Polygon | `selectbypolygon` | `m_BoundaryEntity` = closed line serial, `cb_SelectType` (Inside, Outside, Crossing, Part of, Inside or part of boundary); **OK** | objects by position (the boundary itself is included) |
| Select Similar | `selectsimilar` | `selectEntity` = source serial, then untick `chkAllProperties` and tick only the attributes to match. Only attributes that apply to the source are enabled (a point: Feature code, Feature locked, Layer); **OK** | objects sharing those attributes |
| Advanced (Quick Select) | `quickselect` | scope radio (`m_rbEntireReplace` all data+replace / `m_rbEntireAppend` add / `m_rbCurrentReplace` within current selection); `m_cbObjectType` = data type (e.g. Point, CAD PolyLine ...); "All of this data type" or `m_rbDataWithTheFollowing` + `m_cbProperties` (Attribute, Description 1/2, Easting, Elevation, Feature Code ...) + `m_cbOperator` (`= Equals`, `<> Not equals`, regular-expression variants, ...) + value (`ValueCombo` dropdown for Feature Code, `This_value` text for others); **OK** | e.g. Point with Feature Code = SELB -> exactly that point |
| Invert Selection | `invertselection` (run_command) | acts immediately | everything not selected (16k objects here) |
| Select All | `all` (run_command) | acts immediately | every object (16,299 here) |

## Gotchas

- **Whole-project selections are heavy** (16k objects): clear them (`set_selection serials=[]`) as soon as you have
  what you need. Select All right after an Invert (two whole-project selections back to back) crashed TBC once;
  each on its own was fine.
- Duplicate Points, Elevation and Advanced search the **whole project** unless "Current selection" is chosen; check
  `get_selection` count before acting on it.
- Checkbox lists must be ticked (the fill tool does this); just highlighting an item selects nothing.
