---
name: survey_tools_usage
tbc_versions: ["2026.10"]
category: survey
description: "Verified status and recipes for USING every Survey tab tool (not just opening it): what worked with real values, what is partial or blocked and why, and the exact fields/buttons."
requires_write: true
parameters: []
verified: "2026-10-13 live on TBC 2026.10 a test copy of a production project (tests/survey_cogo_tests.py + interactive runs)"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

> LICENSES DIFFER between users: license notes here (e.g. 'not licensed', ANZ tools) describe the machine where this was written. Check your own with `tbc_license` - search results flag commands your license lacks.
## Read first

- Rules in `working_safely_in_tbc` apply: numeric point IDs + feature codes, wait for Compute Project, close
  panels/views when done, read popups, never raw-delete, read help first.
- Per-command details are also stored as lessons (shown automatically when the command opens) and the panel
  layouts in `knowledge/commands/<key>.json`.
- Do project-wide steps one at a time and save first.

## Status

| Tool (key) | Status | How it works / result |
|---|---|---|
| Rename Points (`renamepoints`) | **works** | select points; "Add constant" + `parameterBox`=1000, untick `chkReport`; OK. 4700483 -> 4701483 |
| Average Points (`createaveragepointcmd`) | **works** | select reference points; Point ID = NEW id as text; Layer; **Add**, then **Compute**. Point at exact average |
| Merge Points (`mergepoints`) | **works** | select points; Identical/Ignored; the extra point arrives with Included=False - tick it with `ui_grid action=set grid=ugMergeDuplicateCandidates ... column=Included value=true` (grid edit mode); OK. 2 duplicates -> 1. |
| Explode Points (`explodepointcmd`) | **works** | Find Explodable Points (nothing selected = whole project; 4339 here); select row in `pointList`; Explode. 102 -> 8 points `102_X`; Undo restores. Merged office points are not explodable |
| Move Survey Point (`movesurveypoint`) | **works** | Point ID = serial (picker), To = target point ID as text; OK. Adds office coordinate; renames `<id>(MOVED)` |
| Transform Survey Points (`transformsurveypoints`) | **works** | select points; `eastingCheckBox`=true, `deltaEasting`=15; Apply; wait for recompute. +15 ft |
| Integrate to Geometry (`geometrypointintegratecmd`) | **works** | select a CLOSED linestring; Starting point ID (next free); **Process**. 4 corner points on the default **Points** layer, skipping existing IDs |
| Single Proportioning (`singleproportioning`) | **works** | Planar; start/end = point IDs; Layer; Starting point ID; `distanceEdit`, `distanceEdit#2`... (rows appear as you fill); Apply. 100.06 measured / 50+50 record -> 50.03 |
| Double Proportioning (`doubleproportioning`) | **works** | for North/East/South/West: radio, `coordinateEdit` (known pt), `bearingEdit` (record azimuth toward the marker), `distanceEdit`; Apply. Point exactly on the marker |
| Create at Station Offset (`createpointsatstationoffsets`) | **works** | Name; Start/End point IDs (WPF, parse on tab-out); row `ClientAreaTextBox#9`=station, `#10`=offset (+ right), `text`=ID; OK. Point on default Points layer + a StationOffsetFactory collection |
| Create Point (`addpoint`) | **works** | see create_point_via_panel |
| Create COGO (`createcogo`) | partial | collection creation works (Options tab -> name, layers, Create). Typed COGO lines (SP/LB...) did not produce linework through automation |
| Legal Description (`descriptionwriter`) | blocked | needs picks in the Plan View ("click on the end of a line segment") |
| New Feature Library (`newfeaturelibrary`) | **works** | Library name; OK. Enables Write FXL to CSV / Convert CSV to FXL |
| Write FXL to CSV (`writefxltocsv`) | **works** | dialog: Target file (type full path), headers; OK. CSV with point/line/polygon definition headers |
| Convert CSV to FXL (`convertcsvtofxl`) | partial | dialog opens; the file must be picked via the Source file '...' Browse button, which automation did not open |
| Process Feature Codes (`processfeaturecodes`) | **works** | tick a source in `PointSourceGrid` (Include); **Process Source(s)**; answer "view report?" No |
| Feature / Occupation / Vector / Optical spreadsheets, Time-Based View | **works (read)** | open as windows; read the UltraGrid (Vector 6850 rows, Optical 225); close the window |
| Merge Survey Projects (`mergesurveyprojects`) | not tested | needs a second .vce project to merge in |
| Internet Download, Send to RTX-PP, Processing Services | not used | user does not use them (online) |
| Loop Closure (`loopclosure`) | not run | acts immediately and opens the report in the browser |
| Process Baselines, Clear Processing, Session Editor, Mean Angle Residuals | n/a | greyed out (no GNSS baselines / MTA data in this project) |
| Adjust Traverse (`adjusttraverse`) | **works** | `<Create New Traverse>` -> name -> Create; pick start station + `addButton`: TBC completes the traverse (201->205->201); Preview Results tab; Apply (67 s recompute). Delete the Traverse object to remove it |
| Total Station Editor (`totalstationeditor`) | partial | select file in the ListView -> OK -> editor dialog opens; editing its contents not automated |
| Disable Redundant BS (`disableredundantbacksights`) | **works** | acts immediately on the whole project; needs `confirm=true` (ask the user) |
| Level Editor / Combine Level | not tested | no level data in this project |
| Adjust Network (`adjustprojectterranet`) | blocked by data | TBC warns "29 unresolved project computation errors"; forcing it raised a protected-memory error. Fix the computation errors first |
| Site Calibration | not tested | opens with a Yes/No question about GNSS base points |
| Local Site Settings (`localsitesettings`) | **works** | Elevation 20 -> 25 -> 20 verified by reopening; each OK recomputes (~68 s) |
| Geoid Sub-Gridding / Datum Gridding | blocked | need .ggf / datum files and drawing a window on a globe |

## Techniques that made the difference (built into the tools)

- Fill the **visible** box when several share a name (Double Proportioning's direction groups).
- WPF entry boxes parse on **tab-out**; Infragistics text boxes, file boxes (`BrowseFile`) and icon-only buttons
  are supported; tabs are selected with `command_ui_click button=<tab name>`.
- Infragistics grid checkboxes: change them through the grid's edit mode (`ui_grid action=set`), not by setting
  the value or clicking.
- Deletion through TBC's Delete command (`delete_entities`), which also deletes selected layers.
