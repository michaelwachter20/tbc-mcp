---
name: drafting_tab_overview
tbc_versions: ["2026.10"]
category: drafting
description: "Every tool on the TBC 2026 Drafting ribbon tab: what it does (from TBC help), command key, help topic, license, what opens (panel fields/buttons, dialog, view window), and which tools act immediately."
requires_write: false
parameters: []
verified: "2026-10-13 live survey on TBC 2026.10 (opened with nothing selected, nothing applied)"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

## Read first

- Read a tool's help before using it: `tbc_help action=read command=<key>` (or the topic number below).
- LICENSES DIFFER between users: the license column reflects the machine that ran this survey; check yours with `tbc_license`.
- 47 tools; 39 licensed on the surveyed machine. The 8 ANZ Toolbox tools (Convert To MText, Explode Text, Find and Replace, Alignment/Excel/Legend Table, Create Slope Markers) need ANZToolbox. Check yours with `tbc_license`.
- No tool acts immediately: each opens a panel, a dialog or a separate editor first. Print commands only print after you press Print in Windows' Print dialog; never press it unless the user asks.
- **Line Type Editor and Symbol Editor start a separate program (PEDITOR.exe)** with its own window. Close it when done (its window's X / CloseMainWindow).
- Just opening **Dimension Style Manager** and cancelling marked the project as modified (TBC adds default style data).
- Prerequisites shown as popups: Edit Text needs exactly one text object selected; Custom Sheet needs a custom sheet set selected; Print Plan Set needs a plan set with sheets.


### Text

| tool | key / help | what it does | opens |
|---|---|---|---|
| Text | `CreateText` / 9979 | Use the Create Text command to add single line or multi-line textual annotations and labels to your data. To create text along a line, see Scenarios below. | panel: Oblique angle [text], Width factor [text], Rotation [text], Height [text], Justification [choice], Text insertion point [text], richTextBox1 [text], Leader type [choice], Text style [choice], Layer [choice]. Buttons: Insert Smart Text, Close, Apply |
| Edit Text | `EditText` / 9979 | Use the Create Text command to add single line or multi-line textual annotations and labels to your data. To create text along a line, see Scenarios below. | needs one text object selected ('Select one text object.') dialog "Warning" |
| Text Style | `textStyleManager` / 6671 | Use the Text Style Manager command to control which styles are available for text in your project and how specific labels in your data appear in graphic views and in printed output. You can select from numerous stroke (vector) ... | dialog "Text Style Manager" |

### Modify Text

| tool | key / help | what it does | opens |
|---|---|---|---|
| Convert To MText | `ANZ_ConvertToMultilineText` / 29734 | Convert to Multiline Text enables you to convert CAD text to CAD Multiline text within TBC. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Explode Text | `ANZ_ExplodeText` / 29826 | The Explode Text command enables you to explode any Text item into linework. This allows for better presentation and export for some third-party packages. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Find and Replace | `ANZ_FindReplaceText` / 29835 | The Find and Replace Text command allows you to perform a simple search and replace of text objects and add a prefix or suffix to existing text. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |

### Dimensions

| tool | key / help | what it does | opens |
|---|---|---|---|
| Create Linear | `CreateLinearDimension` / 17849 | Create dimensions for lines based on point pairs, line segments, and arc segments. | panel: Dimension style [choice], Layer [choice], Dimension style [text], Edit text [bool], Location point [text], Location point [text], Dimension style [text], Two points [radio], Line or arc segment [radio]. Buttons: Close, Apply |
| Create Angular | `CreateAngularDimension` / 17848 | Create dimensions for angles based on point pairs, line segments, and arc segments. | panel: Dimension style [choice], Layer [choice], Edit text [bool], Location point [text], Location point [text], Dimension style [entity], Two line segments [radio], Arc segment [radio]. Buttons: Close, Apply |
| Dimension Style | `DimensionStyleManager` / 17851 | Trimble Business Center allows you to create dimensions for both lines (based on point pairs, line segments, and arc segments) and angles (based on either two lines or an arc segment). When creating a dimension, you must specif... | opening it marks the project modified dialog "Dimension Style Manager" |

### Labels

| tool | key / help | what it does | opens |
|---|---|---|---|
| Label Style Manager | `LabelStyleManager` / 18016 | Use the Label Style Manager to create, edit, and delete label styles for points, lines, and polygons. When creating a label, you must specify the label style you want to use as a template to format the label. You can also label... | dialog "Label Style Manager" |
| Labeling Scale Factor | `PlanarScaleFactor` / 22062 | Use the Labeling Scale Factor command to define a combined scale factor (referred to in this topic more simply as a scale factor) to be used to convert grid distances to ground distances displayed in line segment labels. Two op... | panel: Easting [text], Use geodetics [radio], Northing [text], Use a fixed position [radio], Elevation [text], Define a scale factor for labeling ground distances. [text], Coordinate type [choice], Use a fixed scale factor [radio]. Buttons: Calculate from Selection, Calculate from Selection, Close, Apply |
| Points | `LabelPoints` / 18017 | Create single- or multi-line labels for points using predefined point label styles. | panel: Hide feature code attribute name [bool], Align label to associated line segment [bool], Rotation [text], Select point to label [entity], Multi-select points to label [text], Symbol code [text], Display feature code attributes vertically [bool], Symbol size (mm) [text], Layer [choice], Point label style [text]. Buttons: Add, Remove, ..., Close |
| Lines | `LabelLines` / 18018 | Create single- or multi-line labels for line segments using predefined line label styles. Picking a single segment on a line labels that segment. Selecting multiple lines at once labels every segment of each line. | panel: Keep line direction placement [bool], Minimum line length [text], Add small segments to table [bool], Select segment to label [entity], Minimum line length [text], Layer [choice], Multi-select lines to label [text], Line label style [text]. Buttons: Remove, Add, Close |
| Polygons | `LabelPolygons` / 18019 | Create single- or multi-line labels for polygons using predefined polygon label styles. | panel: Polygon label style [text], Select polygon to label [entity], Layer [choice], Rotation [text], Multi-select polygons to label [text]. Buttons: Remove, Add, Close |
| Leader Lines | `CreateLeaderLines` / 19947 | Use the Create Leader Lines command to move a label and simultaneously create a leader line to "connect" it to its associated object. | panel: Leader position [choice], Display label horizontally [bool], Leader type [choice], Target label [entity], Label insertion point [text]. Buttons: Close, Apply |

### Tables

| tool | key / help | what it does | opens |
|---|---|---|---|
| Points | `CreatePointLabelTable` / 18348 | Create and display in the Plan View and Sheet View a table from selected points that automatically enumerates their attributes (for example, northing, easting, and elevation) based on the selected label table style. | panel: Style [text], Layer [choice], Title [text], LocationCoordinateEdit [text]. Buttons: Cancel, OK |
| Lines | `CreateLineLabelTable` / 18349 | Create and display in the Plan View and Sheet View a table from selected line segments (linestring and polyline segments, rectangle and polygon segments, and arcs and circles) that automatically enumerates their attributes (for... | panel: Style [text], Layer [choice], Title [text], LocationCoordinateEdit [text]. Buttons: Cancel, OK |
| Polygons | `CreatePolygonLabelTable` / 18350 | Create and display in the Plan View and Sheet View a table from selected polygons, rectangles, and circles that automatically enumerates their attributes (for example, perimeter and area) based on the selected label table style. | panel: Style [text], Layer [choice], Title [text], LocationCoordinateEdit [text]. Buttons: Cancel, OK |
| Label Table Style Manager | `LabelTableStyleManager` / 18347 | Trimble Business Center allows you to create and display in the Plan View and Sheet View a table from selected points, lines, and polygons that automatically enumerates their attributes based on the selected label table style. ... | dialog "Label Table Style Manager" |

### Plan View Tables

| tool | key / help | what it does | opens |
|---|---|---|---|
| Alignment Table | `ANZ_InsertAlignmentTable` / 29852 | The Insert Alignment Table command enables you to create a customizable table that describes the horizontal or vertical geometry that was used to create the selected alignment and display it in the plan view. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Excel Table | `ANZ_InsertExcelTable` / 29868 | The Insert Excel Table command enables you to create a table from an excel spreadsheet in csv format and customise the settings for display in the plan view. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Legend Table | `ANZ_InsertLegendTable` / 29869 | The Insert Legend Table command enables you to create legend tables for hatches, line styles, and symbols using the definitions set up in an associated Feature library. Select data from the Project view and create a table conta... | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |

### Blocks

| tool | key / help | what it does | opens |
|---|---|---|---|
| Insert Block | `InsertBlock` / 15469 | Use the Insert Block command to add instances of a block to your model. | panel: Block [choice], Layer [choice], Location 1 [text], Location 2 (not available for this block) [text], Location 3 (not available for this block) [text], Elevation [text], Insert as north arrow [bool], Rotation [text], Scale X [text], Scale Y [text], Scale Z [text]. Buttons: Close, Insert |
| Create Block | `CreateBlock` / 15468 | Use the Create Block command to create one or more CAD block definitions (for example, a north arrow) from lines, text, and other objects. You can then insert instances of the blocks (such as a title block) into your model. | panel: Select objects [text], Name [text], Location 1 [text], Location 2 (optional) [text], Location 3 (optional) [text], Elevation [text], Select objects [text]. Buttons: Close, Create |
| Import Blocks | `ImportBlocks` / 15467 | Use the Import Blocks command to bring one or more block definitions, such as for various north arrows, from CAD files into your project. You can then insert instances of the blocks into your model. Default Trimble blocks that ... | panel: Replace existing blocks [bool], My block folder path [text]. Buttons: Cancel, Import |
| Purge Blocks | `PurgeBlocks` / 15470 | Use the Purge Block command to delete unreferenced (unused and unnested) block definitions from your project. A block definition cannot be purged if: | Apply deletes the checked unused block definitions panel: textBox1 [text]. Buttons: Close, Apply |

### Drafting Objects

| tool | key / help | what it does | opens |
|---|---|---|---|
| Create Slope Markers | `ANZ_CreateSlopeMarkers` / 29790 | The Create Slope Markers command enables you to select a control line and two other lines, generally the top and toe of an embankment, and create markers between them perpendicular to the control line at nominated intervals. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Create Hatch | `createhatch` / 17165 | Use the Create Hatch command to create a hatch pattern and apply it to a region in a sheet view to identify the area as having a specific material on screen and on plotted sheets. Once created, you can explode a hatch object in... | panel: Hatch boundaries [text], Layer [choice], Pattern [choice], Scale [text], Angle [text]. Buttons: Preview, Close, Apply |
| Quick Profile | `CreateQuickProfile` / 25028 | Create and Edit 'Quick Profile' Cross-Sections of a Site | panel: TextBox [text], Surfaces (for profile table) [choice], ComboBox#2 [choice], ComboBox#3 [choice], Define [radio], From [text], To [text], Text style [choice], Use existing line [radio], ClientAreaTextBox#3 [text], Quick profile name [text], Layer [choice], Quick profile location [text], Settings [choice]. Buttons: OK, Cancel, Options |

### Templates

| tool | key / help | what it does | opens |
|---|---|---|---|
| Drafting Templates | `DraftingTemplates` / 13912 | Use the Drafting Templates command import from a variety of pre-defined drafting templates that include a plan set and one or more sheet sets. Any of the settings from these templates or your own plan sets and sheet sets can be... | no panel appeared with nothing selected no panel/dialog/window (acts directly or needs a selection) |

### Plan View

| tool | key / help | what it does | opens |
|---|---|---|---|
| Print Plan View | `PrintPlanView` / - |  | panel creates a plotbox; printing happens only from Windows' Print dialog panel: Template [choice], Name [text], Scale [text], Location [text], Rotation [text]. Buttons: Create, Print, Close |
| Print By Selection | `PrintBySelection` / 280 | You can print the contents of a graphic view or a selected plotbox to any Windows-supported printing device. You can also print a report using your default Web browser's print command. | printing happens only from Windows' Print dialog panel: no fields. Buttons: Cancel, Apply |

### Sheet Layout

| tool | key / help | what it does | opens |
|---|---|---|---|
| Create Dynaview | `CreateDynaView` / 15978 | Use the Create Dynaview command to add a frame around a portion of your model to have the frame's contents display at a location in paper space (in a Sheet View). Establish the size and shape of a dynaview by creating a frame (... | panel: Frame (on a Plan View) [entity], View filter [choice], Rotation [text], Scale [text], Location (on a sheet) [text], Layer [choice], Name (optional) [text]. Buttons: Close, OK |
| Create Dynaview Boundary Set | `CreateDynaViewBoundaryCollection` / 17167 | Create and Edit a Dynaview Boundary Collection | panel: Rotation [text], First sheet origin [text], Layer [choice], Y overlap [text], X overlap [text], Rows [number], Columns [number], Plot scale [text], Height on paper [text], Width on paper [text], Name [text]. Buttons: Close, Apply |
| Create Scale Bar | `CreateScaleBar` / 19961 | Use the Create Scale Bar command to create a scale line, alternating, or double-alternating scale bar to display in the Plan View or a dynaview in your project. | panel: Specify scale [radio], Target dynaview [radio], Scale bar type [choice], Scale bar type [entity], Location [text], Layer [choice], Prefix [text], Position [choice], Text style [choice], Format [choice], Display scale label [bool], Position [choice], Text style [choice], Left sheet unit per bar unit [text], Number of left divisions [choice], Right sheet unit per bar unit [text], Number of right divisions [choice], Height [text]. Buttons: Cancel, OK |
| Insert Image | `InsertImage` / 18312 | Use the Insert Image command to place an image in a Plan View, Sheet View and Profile View. For example, you can insert your company logo on a set of sheets that you want to plot. | panel: File name [text], Lower corner [text], Layer [choice], Scale [text]. Buttons: Close, Apply |
| Copy to Sheet | `CopyToSheet` / 16401 | Use the Copy to Sheet command to copy objects from any view to a plan set, sheet set, or custom sheet. Doing this can help you: | panel: Sheet [text], Objects to move [text]. Buttons: Close, Apply |
| Grid Style | `GridStyleManager` / 17166 | Use the Grid Style Manager command to create and edit a variety of grid styles to use on dynaviews placed in sheet views. Using grid styles, you can control how gridlines, labels, ticks, and station equations appear on sheets b... | dialog "Grid Style Manager" |

### Plan Set

| tool | key / help | what it does | opens |
|---|---|---|---|
| Plan Set | `CreatePlanSet` / 13905 | To prepare for printing/plotting onto one or more sheets, use the Create Plan Set command to create a top-level collection for your entire set of plans. The plan set is a container for one or more sheet sets. You can also save ... | panel: Name [text]. Buttons: Cancel, OK |
| Create Sheet Set | `CreateSheetSet` / 13906 | Use the Create Sheet Set command to create a second-level collection (beneath a plan set) that contains elements that you want to appear on every sheet in a common set of sheets. You can create these types of sheets sets: | panel: Plan set [text], Sheet set name [text], Sheet set type [choice], Paper size [choice], Portrait [radio], Landscape [radio], Sheet width [text], Sheet height [text], Corridor [text]. Buttons: Cancel, OK |
| Custom Sheet | `CreateCustomSheet` / 16292 | Use the Create Custom Sheet command to manually create individual unique sheets, such as a title page or a sheet with objects from other views presented in one or more dynaviews. | needs a custom sheet set selected first dialog "There was a problem adding a custom sheet." |

### Print

| tool | key / help | what it does | opens |
|---|---|---|---|
| Print Plan Set | `PrintPlanSet` / 16339 | Use the Print Plan Set command to print/plot one or more sheets from a plan set. You can plot to any of the printing or plotting devices supported by Windows. | needs a plan set with sheets ('No plan set was found ...') dialog "No plan set was found in the current project. Create a plan set and add sheets prior to printing." |
| Create 3D PDF | `Create3dPDF` / 16056 | Create a 3D Portable Document File (.pdf) | panel: m_OutputFile [text], m_UserName [ultra], m_Description [ultra], IncludeIcon [ultra], ModifyProjectSettings [ultra], m_Phone [ultra], m_Email [ultra], m_Website [ultra], m_CompanyName [ultra]. Buttons: Cancel, OK, ... |

### Advanced

| tool | key / help | what it does | opens |
|---|---|---|---|
| Line Style Manager | `LineStyleManager` / 3850 | Use the Line Style Manager command to control which line styles are available to apply to lines in your project and how specific lines appear in graphic views and in printed output. You can define line styles and weights for ea... | dialog "Line Style Manager" |
| Line Type Editor | `LineTypeEditor` / 13858 | Use the Line Type Editor to create and edit line styles that can then be accessed in Trimble Business Center through the Line Style Manager command. The line types that you create and edit in the editor become the line types in... | starts PEDITOR.exe (separate 'Line Type Editor' window) no panel/dialog/window (acts directly or needs a selection) |
| Symbol Manager | `SymbolManager` / 1591 | Control which symbols are available for features in your project and how specific features in your data appear in graphic views and in printed output. You can import symbols from symbol (.sym) files. In addition, you can import... | dialog "Symbol Manager" |
| Symbol Editor | `SymbolEditor` / 16304 | Use the Symbol Editor to create and edit symbols that can then be accessed in Trimble Business Center through the Symbol Manager command. The point symbols that you create and edit become the symbols in the software and Feature... | starts PEDITOR.exe (separate 'Symbol Editor' window) no panel/dialog/window (acts directly or needs a selection) |
