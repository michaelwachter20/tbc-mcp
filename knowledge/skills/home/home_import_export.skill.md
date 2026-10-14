---
name: home_import_export
category: home
description: "Verified recipes for Home > Import and Export through the tbc_import / tbc_export tools: exporters per category, CSV / DXF / LandXML export, CSV point import, the Import Format Editor wizard, project-folder copies, DXF import, and why import records must never be deleted."
requires_write: true
parameters: []
tbc_versions: ["2026.10"]
updated: 2026-10-14T09:54:47
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.
## Use the tools

- **Export:** `tbc_export action=formats` lists every exporter by category; `tbc_export category=<tab> format=<exporter>
  serials=[...] path=<full path>` exports and returns the file size. Never the project folder unless the user asks;
  never Remote Save (online).
- **Import:** `tbc_import action=scan folder=<folder>` shows each file with the importer TBC detected - **check it**.
  Then `tbc_import action=import folder=... files=[...] confirm=true` after asking the user.

## Export (verified)

| Category tab | Exporter | Result |
|---|---|---|
| Custom | `P,N,E,elev,Code` | one CSV row per point: ID, northing, easting, elevation, feature code (exact) |
| CAD | `DXF exporter` | linework as POLYLINE (points as POINT) |
| Construction | `LandXML exporter` | LandXML with every point ID |

Categories and counts on 2026.10: GIS 9, Construction 28, CAD 8, Custom 5, Points 21, Survey 21, Point Cloud 12,
Mobile Mapping 12, Corridor 8.

How the pane works: category = `GroupTab` (UltraTabStrip), exporter = `FormatList`; the panel rebuilds per exporter,
so find the data box by its "Selected: N" value; `TargetFileBox` = full path; press **Export**.

## Import (verified for CSV points)

- The Import pane is WPF, driven by `ImportCommand.ViewModel`: `RequestedPath` = folder (it scans; wait until
  `ImporterScanningInProgress` is false), files selected through the pane's grid adapter (`SetSelection`), then Import.
- **The detected importer can be wrong**: a P,N,E file was detected as `P,E,N,elev,Code (Control)` (northing/easting
  would swap). Write/choose files in the detected order, or pick the file type in TBC first.
- CSV formats open the **Import Format Editor** wizard while an "Importing File" progress window waits; its **Import**
  button imports with that format (Cancel aborts). Points go to the default **Points** layer; TBC then recomputes
  (~2 min on the test project).
- **TBC copies every imported file into the project folder.** Tell the user the file names (the user chose to keep
  such copies).
- Undoing an import: delete the imported **data** (points/objects) only. **Never delete the import's `FileProperties` record**
  (named after the file): on 2026.10 that left a broken imported-file entry and the NEXT import failed inside TBC
  ("Object reference not set...", then "unexpected error"; error report: ImportCommandViewModel.UpdateFiles
  NullReferenceException while RawDataContainer recalculated). `delete_entities` refuses these records.

## DXF / DWG import (verified)

- AutoCAD importer; a DXF that TBC exported itself imported cleanly right after a CSV import: linework as
  `ForeignCad.Poly3D` on the DXF's own layer, plus a CadImportDataBlock, FileProperties and ImportSelection.
- Two earlier DXF imports failed ("Object reference not set...", then "unexpected error"). TBC's error report showed the
  failure in the Import pane's imported-file list, caused by the test having **deleted the previous import's record**.
  With records left alone it works - so never delete import records.
