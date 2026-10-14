---
name: cad_tab_overview
tbc_versions: ["2026.10"]
category: cad
description: "Every tool on the TBC 2026 CAD ribbon tab: command key, license status, and what opens (panel fields and buttons, or popup), from a live survey."
requires_write: false
parameters: []
verified: "2026-10-13 survey on TBC 2026.10 (opened with nothing selected, nothing applied)"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

> LICENSES DIFFER between users: license notes here (e.g. 'not licensed', ANZ tools) describe the machine where this was written. Check your own with `tbc_license` - search results flag commands your license lacks.
## How to use this

Open a tool with `command_ui_open key=<key>` (the license is checked first). Most panels want objects: select them
first with `set_selection serials=[...]`, or fill the panel's selection field. Tools marked **not licensed** need the
ANZ Toolbox and are refused automatically. Detailed recipes live in their own skills (layer_manager,
create_point_via_panel, ...). Field lists below are in panel order; [kind] is text/choice/bool/radio/list.


### Layers

| tool | key | result |
|---|---|---|
| Layer Manager | `LayerManager` | toggles the Layer Manager pane (see the layer_manager skill) |
| Layer Groups | `LayerGroupManager` | panel **Layer Group Manager**: no fields. Buttons: Delete, New, Close |
| Relayer Objects | `RelayerObjects` | panel **Relayer Objects**: Multi-select objects to relayer [text], Target layer [choice], Select objects to relayer [text]. Buttons: Apply, Close, Options |
| Standardize | `StandardizeLayers` | panel **Standardize Layers**: m_AllLayersList [list]. Buttons: Close, Apply |
| Regroup Layers | `ANZ_RegroupLayers` | not licensed (skipped, needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Delete layers | `ANZ_DeleteLayers` | not licensed (skipped, needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |

### Points

| tool | key | result |
|---|---|---|
| Create Point | `AddPoint` | panel **Create Point**: Measure Codes mode [bool], Layer [choice], Feature code [text], Point ID [text], Status [choice], Height [text], Northing [text], Easting [text], Elevation [text], Coordinate type [choice]. Buttons: Close, Add |
| Convert CAD Points | `ConvertCADPoints` | popup: "No CAD points are selected." |
| Convert To CAD | `ANZ_ConvertToCADPoints` | not licensed (skipped, needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Create at Intervals | `CreateAtInterval` | panel **Create Points at Intervals**: Two points [radio], Selection [radio], memberSelection1 [text], Point quality [choice], Vertical offset [text], Create grid-only points [bool], Horizontal offset [text], Layer [choice], Feature code [text], Add points at start and end position [bool], Add points at intermediate line vertices [bool], Add points at vertical transitions [bool], Interval [text], Starting point ID [text]. Buttons: Close, Apply |
| Station Offset | `ANZ_PointsFromChainageOffset` | not licensed (skipped, needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Create from CAD | `CreateFromCAD` | panel **Create Points from CAD**: Point quality [choice], Selection [text], Create grid-only points [bool], Centroids of closed lines [bool], Segment end points [bool], Intersections [bool], Insertion points [bool], CAD points and mesh vertices [bool], Arc/circle centers [bool], Line mid points [bool], Line end points [bool], Starting point ID [text], Layer [choice], Feature code [text]. Buttons: Close, Apply |
| Create from BIM | `CreateFromBimCmd` | panel **Create Points from BIM**: Select BIM objects [text], Create from mesh centroids [bool], Use individual mesh centroids [radio], Use BIM geometry centroids [radio], Use BIM properties [radio], Create from mesh faces [bool], Use all selected mesh faces [radio], Use all horizontal mesh faces [radio], Use lowest horizontal mesh faces [radio], Use pipe/beam end faces [radio], Create grid-only points [bool], Point quality [choice], Starting point ID [text], Layer [choice]. Buttons: Apply, Close, Options |
| Integrate to Geometry | `GeometryPointIntegrateCmd` | panel **Integrate to Geometry**: Select points and geometry [text], Starting point ID [text]. Buttons: Close, Options, Process, Clear |
| Find and Replace | `ANZ_FindAndReplacePoints` | not licensed (skipped, needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |

### Edit Objects

| tool | key | result |
|---|---|---|
| Map Objects | `ANZ_MapObjects` | not licensed (skipped, needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Map and Export | `ANZ_MapAndExport` | not licensed (skipped, needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Match Properties | `MatchProperties` | panel **Match Properties**: Target object [text], Match properties for all object types [bool], Target object [text], Source object [text], Color [bool], Line style [bool], chkFeatureAttribute [bool], Block scale [bool], Feature locked [bool], Label table style [bool], Feature code [bool], Label style [bool], Block rotation [bool], Name [bool], Dimension style [bool], Text style [bool], Weight [bool], Line style scale [bool], All properties [bool], Layer [bool]. Buttons: Select target attributes, Close, Apply |
| Rename Objects | `ANZ_RenameObjects` | not licensed (skipped, needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Name Objects | `NameObjects` | panel **Name Objects**: Object to name [text], New name [text], Results [text]. Buttons: Select Unnamed Objects, Close, Apply |
| Remove Duplicates | `ANZ_RemoveDuplicates` | not licensed (skipped, needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Change Elevation | `ChangeElevation` | panel **Change Elevation**: Objects to elevate [text], Delta elevation [radio], Absolute elevation [radio], Undefined elevation [radio], Surface elevation [radio], Relative to point [radio], Elevation [text]. Buttons: Close, Apply |
| Drape Objects | `DrapeObjectsOnSurface` | panel **Drape Objects On Surface**: Select multiple [bool], Surface sharpness [choice], Reference line/point [text], Surface [text], Layer [choice]. Buttons: Close, Apply |
| Drape Objects | `DrapeObjectsOnPointCloud` | panel **Drape Objects**: CAD objects selection [text], Point cloud selection [text], Search Strategy [choice], Search distance [text], Offset lines [bool], Creation Options [text], choice [choice], Add point when interval exceeds [bool], ClientAreaTextBox#3 [text], Interpolate missing elevations for lines [bool], Layer [choice], Delete the existing objects [bool]. Buttons: Apply, Cancel |

### Move/Transform

| tool | key | result |
|---|---|---|
| Move | `MoveObjects` | panel **Move Objects**: Delta elevation [text], Objects to move [text], From [text], To [text], 3D move [bool], Update dependent objects when dragging [bool], Show preview [bool]. Buttons: Close, Apply |
| Rotate | `RotateObjects` | panel **Rotate Objects**: Angle [text], Objects to rotate [text], Around [text], Update dependent objects when dragging [bool], Show preview [bool]. Buttons: Close, Apply |
| Scale | `ScaleObjects` | panel **Scale Objects**: Horizontal (Y) scale [text], Lock X and Y scales [bool], From [text], Horizontal (X) scale [text], Objects to scale [text], Scale vertical [bool], Base elevation [text], Vertical scale [text]. Buttons: Close, Apply |
| By Points | `RotTransSclObjectsByPoints` | panel **Move/Rotate/Scale Objects by Points**: Point 1 [text], Point 2 [text], Point 1 [text], Point 2 [text], Scale [text], Rotation angle [text], Delta elevation [text], Objects to move [text], 3D move [bool]. Buttons: Cancel, OK |
| Transform Survey Points | `TransformSurveyPoints` | panel **Transform Survey Points**: H. Residual [text], V. Residual [text], enableCheckBox [bool], fromPoint [text], toPoint [text], Fix vertical scale at 1.00 [bool], Objects to transform [text], X Rotation [bool], Objects to transform [text], Y Rotation [bool], First "From point" [radio], Centroid [radio], Delta Northing [bool], Objects to transform [text], Delta Easting [bool], Objects to transform [text], Objects to transform [text], Objects to transform [text], Delta elevation [bool], Objects to transform [text], Z Rotation (delta azimuth) [bool], Horizontal scale [bool], Objects to transform [text], Least squares [radio], Helmert [radio]. Buttons: Close, Apply |
| Transform | `RotTransSclObjects` | panel **Move/Rotate/Scale Objects**: Horizontal scale [text], Rotation angle [text], Delta elevation [text], Objects to move [text], From [text], To [text], 3D move [bool]. Buttons: Close, Apply |
| Mirror | `MirrorObjects` | panel **Mirror Objects**: Delete source objects [bool], From [text], To [text], Objects to mirror [text]. Buttons: Close, Apply |

### Clone

| tool | key | result |
|---|---|---|
| Copy | `CopyObjects` | panel **Copy Objects**: Relayer copied objects [bool], Objects to copy [text]. Buttons: Close, Apply |
| Array | `ANZ_Array` | not licensed (skipped, needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |

### Copy/Paste

| tool | key | result |
|---|---|---|
| Copy | `Copy` | copies the current selection to the clipboard (no UI) |
| Paste | `Paste` | disabled on ribbon (skipped) |
| Paste special | `PasteSpecial` | panel **Paste special**: Paste method [choice]. Buttons: OK, Cancel |

### Explode

| tool | key | result |
|---|---|---|
| Explode | `Explode` | panel **Explode**: Delete blocks after exploding [bool], Objects to explode [text]. Buttons: Close, Explode |

### Images

| tool | key | result |
|---|---|---|
| Georef Image | `georeferenceImage` | panel **Georeference Image**: cepImage [text]. Buttons: Delete, Add, Close, Compute |
| Georef Vector PDF | `GeoReferenceVectorPdf` | popup: "No PDF file is defined in the project." |
| Import Vector PDF | `ImportVectorPdfData` | panel **Import Vector PDF Data**: Preserve native PDF layers [radio], Layer by style [radio], Do not join dashed lines [radio], Join dashed lines and preserve raw data [radio], Join dashed lines and discard raw data [radio], Georeferenced vector PDF pages [ultra], Georeferenced vector PDF pages [ultra], Georeferenced vector PDF pages [ultra]. Buttons: Close, Import |
| Place Image | `PlaceImage` | panel **Place Image**: m_cmbGeorefedImages [choice], Bearing [text], To pixel [text], From pixel [text], Distance [text], To pixel [text], From pixel [text], Known distance [radio], Line with distance and bearing [radio], Scale bar and known bearing [radio]. Buttons: Close, Compute |
| Capture | `Capture` | panel **Capture Image...**: Select plotbox (optional) [text], File name [text], Resolution [choice]. Buttons: Close, Apply |
| Boundaries | `ImageBoundaries` | panel **Add/Remove Image Boundaries**: Clipping boundary [text]. Buttons: Close, Add, Remove |
| Copy View | `CopyViewToClipboard` | copies the current view image to the clipboard (no UI) |

## Gotchas

- Convert CAD Points with nothing selected shows the popup "No CAD points are selected." Select CAD points first.
- Georef Vector PDF needs a PDF already in the project ("No PDF file is defined in the project.").
- Paste is greyed out until something has been copied.
- Integrate to Geometry's ribbon key is `DuplicateCmd.1.GeometryPointIntegrateCmd`; its command key is `geometrypointintegratecmd`.
- Copy and Copy View overwrite the Windows clipboard.
- Usage beyond opening the panels is recorded per tool in the `cad` skills as each one is verified.
