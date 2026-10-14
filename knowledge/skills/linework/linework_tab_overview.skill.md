---
name: linework_tab_overview
tbc_versions: ["2026.10"]
category: linework
description: "Every tool on the TBC 2026 Linework ribbon tab: what it does (from TBC help), command key, help topic, license, what opens (panel fields/buttons, dialog, view window), and which tools act immediately."
requires_write: false
parameters: []
verified: "2026-10-13 live survey on TBC 2026.10 (opened with nothing selected, nothing applied)"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

## Read first

- Read a tool's help before using it: `tbc_help action=read command=<key>` (or the topic number below).
- LICENSES DIFFER between users: the license column reflects the machine that ran this survey; check yours with `tbc_license`.
- Every tool here opens a command panel; none acts immediately. 24 Linework tools are ANZ Toolbox / SiteModeling on the surveyed machine (check yours with `tbc_license`).
- Creating linework: Polyline (constant elevation), Linestring (2D/3D, most versatile), Boundary, Breakline, Polygon, Circle/Arc/Rectangle variants, Best-Fit Line, Quick Line (Trimble macro).
- For USING the tools (verified recipes) read **linework_tools_usage**.


### Direction

| tool | key / help | what it does | opens |
|---|---|---|---|
| Show Direction | `ANZ_ShowLineDirectionOptions` / 29943 | The Show Line Direction Options command shows the direction (plan and 3D view) of selected lines. It does not require a command to be open to operate. The command is used to turn direction arrows on and off, and set their color... | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Reverse | `ANZ_ReverseLines` / 30004 | The Reverse Lines command enables you to reverse multiple linear objects at the same time. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Set Direction | `ANZ_SetLineDirection` / 30008 | The Set Line Direction command enables you to pick a reference line/alignment, then select linestrings that it will switch to run the same direction as the reference. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |

### Create

| tool | key / help | what it does | opens |
|---|---|---|---|
| Polyline | `CreatePolyline` / 10424 | Use the Create Polyline command to create a multi-segment line at a constant elevation by either picking each segment's start and end points or by streaming points. (To create a linestring that has multiple elevations, see Crea... | panel: Elevation [text], Automatically close by connecting ends [choice], Layer [choice], Name [text], Stream points [radio], Specify individual points [radio], Next point [text]. Buttons: Add Point, Close, New |
| Linestring | `CreateLinestring` / 5444 | Create linestrings (versatile single or multi-segmented linear or curvilinear objects) to represent 2D or 3D linear objects. 3D lines can be defined and queried entirely from within the Plan View, and they provide a unique and ... | panel: Name [text], Layer [choice], Line style [choice], Line style scale [text], Color [choice], Extend vertical [bool], Surface sharpness [choice], Auto-close [bool]. Buttons: Cancel, OK |
| Boundary | `CreateBoundary` / 20865 | - Create a 2D boundary to delineate a portion of a surface. This is useful if you do not want to send an entire surface to field device firmware; it enables you to include a smaller surface model with your design data. The boun... | panel: Name [text], Layer [choice], Usage [choice], Alignment corridor [radio], Polygon [radio], Polygon (from a line) [radio], Point [text], Additional point [text]. Buttons: Apply, Close, OK |
| Breakline | `CreateBreakLine` / 1533 | 3D lines of several types can be designated as members of a surface. They serve to influence the shape of that surface by acting in the classic manner as breaklines. These lines can exhibit complex curvilinear geometry and stil... | panel: Add to surface [text], Surface sharpness [choice], Layer [choice], Name [text]. Buttons: Cancel, OK |
| Polygon | `CreatePolygon` / 11048 | Create polygons to represent 2D or 3D polygonal objects that display in the graphic views. You can create polygons in the software, or you can convert imported polygons, such as CAD polygons and polygon features, and edit as ne... | panel: Name [text], Layer [choice], Border line style [choice], Border line style scale [text], Border color [choice], Extend vertical [bool], Surface sharpness [choice], Fill color [choice], Fill transparency [text]. Buttons: Cancel, OK |
| Outline | `CaptureOutline` / 29200 | Capture Outlines from Measured or Scanned Points | panel: Name (optional) [text], Feature (optional) [choice], Layer [choice], Elevation [text], Coordinate [text]. Buttons: Ok, Cancel, Undo last coordinate, Finish outline, Close outline |
| Create Circle | `CreateCircle` / 10795 | Use the Create Circle command to draw a 360° arc at a constant elevation. Using the auto-advance mode, you can quickly create multiple circles with the same radius. Once created, circles can also be copied, moved, or scaled. | panel: Name [text], Layer [choice], Elevation [text], Center point [text], Radius [text]. Buttons: Create, Cancel |
| Three-Point Circle | `CreateThreePointCircle` / 21020 | Use the Create Three-Point Circle command to create a circle by selecting three points and/or coordinates on its circumference. This is especially useful when working with point clouds where you can use a limit box or cutting p... | panel: Name [text], Layer [choice], Elevation [text], Point three [text], Point two [text], Point one [text]. Buttons: Close, Apply |
| Arc | `CreateArc` / 13280 | Use the Create Arc command to create an arc at a constant elevation using various creation options. The positive direction for creating an arc (using any of the options) is clockwise. | panel: Name [text], Layer [choice], Elevation [text], Create arc using [choice], Start point [text], Middle point [text], End point [text]. Buttons: Apply, Close |
| Chord | `ANZ_CreateChordLines` / 29811 | The Create Chord Lines command enables you to select one or more linestrings and set a chord distance to create individual line segments at that length, to be applied in 2D or 3D from the start of the line. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Rectangle | `CreateRectangle` / 14049 | Use the Create Rectangle command to quickly draw rectangular polylines. Using the auto-advance mode, you can quickly create multiple rectangles. Once created, rectangles can also be copied, moved, or scaled. | panel: Name [text], Layer [choice], Elevation [text], Corner one [text], Corner two [text]. Buttons: OK, Cancel |
| Three-Point Rectangle | `CreateThreePointRectangle` / 21041 | Use the Create Three-Point Rectangle command to create a rectangle by selecting three points and/or coordinates. Two points define the corners for one side of the rectangle; the third point defines where to draw the opposite si... | panel: Width [text], Name [text], Corner two [text], Layer [choice], Corner one [text], Elevation [text]. Buttons: Close, Apply |
| Best-Fit Line | `BestFitLine` / 19745 | Use the Best-Fit Line command to automatically create a straight or curved "best-fit" line based on the 2D or 3D survey, CAD, and/or scan points you select. This can be helpful, for example, when working with point clouds and c... | panel: Selected points [text], Polynomial degree [number], Line type [choice], memberSelection [text], Layer [choice]. Buttons: Apply, Cancel, OK |
| Best Fit Circle | `ANZ_BestFitCircle` / 29735 | Create Best Fit Circle enables you to select at least 3 points and fit a circle using the least squares method. A preview is available to check the resulting delta values from the original points to the created circle. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Quick Line | `QuickLine` / 22055 |  | panel: Name [text], Layer [choice], Coordinate [text], Elevation [text]. Buttons: New, Apply, Close |

### Convert

| tool | key / help | what it does | opens |
|---|---|---|---|
| To Linestring | `ANZ_ConvertToLinestring` / 29729 | Convert to Linestring enables you to convert alignments, polylines, and CAD line objects into Linestring objects. Additionally, it enables you to remove UCS (User Defined Coordinate Systems) from imported CAD objects or from ob... | panel: Select entities [text], DeleteExisting [bool], ConvertAlignments [bool], AllowLeaders [bool], ConvertUcs [bool], Horizontal arc tolerance [text], Vertical arc tolerance [text], Override layer and color [bool], Layer [choice], Color [choice], Auto convert to linestrings on import [bool]. Buttons: Apply, OK, Close, Options |
| To Horizontal | `ANZ_ConvertToHorizontalLinestring` / 29728 | The Convert to Horizontal Linestring command enables you to convert linestrings containing vertical data to horizontal data only, by linearising curves using a chord to arc tolerance. It will also add the calculated height at "... | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| To Polygon | `ANZ_ConvertToPolygon` / 29749 | Convert to Polygon enables you to convert closed CAD polylines and Linestrings into Polygons. This command converts horizontal and vertical arc data to straight line segments in the process. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |

### Edit

| tool | key / help | what it does | opens |
|---|---|---|---|
| Offset | `OffsetLinestring` / 7349 | Use the Offset Line command to create a new linestring offset at a specified distance from an existing line. The line from which you are offsetting can be either 2D (such as a boundary, polyline, circle, or an alignment without... | panel: Vertical offset [text], Name [text], Line to offset [entity], Offset distance [text], Side to offset [text], Layer [choice], Offset a segment [bool], Starting point [text], Ending point [text]. Buttons: Close, Apply |
| Variable Offset | `VariableOffsetLine` / 19917 | Use the Variable Offset Line command to create a linestring offset at varied distances from an existing line. The line from which you are offsetting can be either 2D or 3D with an elevation or slope. | not licensed (needs one of ['SiteModeling']) |
| Move | `ANZ_MoveLine` / 29940 | The Move Line command enables you to select a line or multiple lines and move them without needing to copy and offset. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Merge | `ANZ_MergeLines` / 29935 | The Merge Lines command enables you to select one linestring and a new linestring, then remove the section of the original line where the new line is located. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Append Tracked | `AppendTrackedLine` / 13279 | Create Linestring Segments from a Tracked Line | panel: End clip [text], Start clip [text], Line to append [entity], Base line [entity]. Buttons: Close, Append |
| Fillet Chamfer | `FilletChamfer` / 19946 | Use the Fillet/Chamfer command to create a fillet line segment or chamfer line segment for two non-parallel line or arc segments. | panel: Apply to entire line [bool], Fillet radius [text], Target line segments [entity], Target line segments [entity], Trim object [bool], Chamfer [radio], Fillet [radio]. Buttons: Close, Apply |
| Trim Extend | `TrimExtendLines` / 8240 | - Lengthen (1 below) or shorten (2) selected lines to their planimetric intersection with a specified bounding line (in yellow). | panel: Multiple lines to bounding lines [radio], One line to bounding lines [radio], One line by distance [radio], Trim/extend shortest distance [radio], Bounding lines [text], Extend [radio], Trim [radio], Line to trim or extend [entity]. Buttons: Close, Apply |
| Extend to Surface | `ANZ_ExtendLinesToSurface` / 29831 | The Extend Lines to Surface command enables you to select one or multiple lines and extend them on grade to intersect a surface, extend to a set Elevation, or extend by a slope distance. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Divide Lines | `DivideLine` / 21668 | Divide an Existing Line into Multiple Segments | panel: Slope length [radio], Horizontal length [radio], dedDivideLength [text], numUpDownDivideNum [number], Divide by length [radio], Divide by number of separated objects [radio], Select a segment to divide [entity], Multi-select lines to divide [text]. Buttons: Close, Apply |
| Break | `BreakLine` / 5966 | Break a line to split it into two separate linestrings at the point you specify. The linestrings remain coincidental at the break point, but must be edited separately thereafter. | panel: Line [entity], Distance along [text]. Buttons: Close, Break |
| Explode Lines | `ANZ_ExplodeLines` / 29825 | The Explode Lines command enables you to explode any linework into ether all segment elements or segments based on user defined deflection angle. | panel: Lines [text], CheckBoxRelayer [bool], ComboBox [choice], Delete existing [bool], Every segment [radio], Large deflections [radio], Max angle [text]. Buttons: Apply, Close, Options |
| Join | `JoinLines` / 6154 | Join two or more contiguous lines into individual linestrings using manual and automated methods. When lines are joined, they are converted into linestrings, thereby increasing their versatility. The resulting linestring's dire... | panel: Lines to join [text], All selected lines [radio], Lines to join [text], Base line [entity], One line to selection [radio], Two lines [radio], Line to join [entity], Base line [entity]. Buttons: Close, Join |
| Clip | `ClipLines` / 9307 | Clip Lines or Break Lines at Bounding Lines | panel: Break lines at crossing lines [radio], Remove lines outside bounding lines [radio], Remove lines inside bounding lines [radio], Lines to clip [text], Closed bounding lines [text]. Buttons: Close, Apply |
| Insert/Delete Nodes | `ANZ_InsertDeleteNodes` / 29853 | The Insert/Delete Nodes command enables you to adjust linestring geometry by inserting and deleting nodes at defined locations. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Insert Segment | `StandardInsertLineSegment` / 22996 | Insert a Segment into a Linestring or Polyline | panel: Line [text], Location [text], Elevation [text]. Buttons: Insert, Close |
| Segment Count | `ANZ_SegmentCount` / 30007 | The Segment Count command enables you to count the total number of horizontal segments in the selected lines. This is useful for checking the segment numbers of avoidance zone polygons, which have a maximum number allowed in Ea... | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Delete | `DeleteLineSegment` / 6175 | Delete a segment from a multi-segmented line or linestring to form one or two linestrings, depending on whether you delete an interior or an end segment. If a line consists of only one segment, the entire line will be deleted. ... | panel: Line [entity], list [list]. Buttons: Close, Delete |
| Simplify | `ANZ_SimplifyLineStrings` / 30013 | The Simplify Linestrings command enables you to select one or more lines to remove unnecessary segments from the lines, and convert horizontally chorded linework to curvilinear linestrings. This is ideal for converting segmente... | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Insert Vertices | `ANZ_InsertVerticesFromPoints` / 29870 | The Insert Vertices from Points command enables you to select a line and some points to create new vertices (and optionally, points) from points. Depending on the mode selected, the new nodes are created on the line perpendicul... | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Integrate to Geometry | `GeometryPointIntegrateCmd` / 27530 | Use the Integrate Points into Geometry command to automatically convert vertex coordinates for linestring-based polygonal objects and COGO parcels into points. | panel: Select points and geometry [text], Starting point ID [text]. Buttons: Close, Options, Process, Clear |
| Unlink | `ANZ_UnlinkLinestrings` / 30035 | The Unlink Linestrings command enables you to convert a linestring using Point IDs for its location into a coordinate-based linestring. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Edit Elevation | `ANZ_EditLinestringElevation` / 29805 | The Edit Linestring Elevation command enables you to select a linestring, optionally nominate beginning and end chainages, and select one of three modes (none, constant, interpolate) to edit the elevations within that chainage ... | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Set Line Elevation | `SetLineElevation` / 6156 | Apply a single, constant elevation to a 2D line to make it a 3D linestring. You can also specify a vertical offset from the elevation that you enter and a surface to which the linestring will be added. | panel: Elevation [text], Line [entity], Add to surface [text], Vertical offset [text]. Buttons: Close, Apply |
| Adjust Profile | `ANZ_AdjustProfile` / 29676 | The Adjust Profile command allows you to select one or many linestrings and apply a vertical adjustment to the profile of the string using serval different methods. This command is particularly useful for creating new strings a... | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |

### Check

| tool | key / help | what it does | opens |
|---|---|---|---|
| Node Cleanup | `ANZ_LineNodeCleanup` / 29892 | The Line Node Cleanup command enables you to clean up duplicate nodes on a linestring, adjust vertical segments, and remove node heights outside the set range. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Compare Lines | `ANZ_CompareLines` / 29774 | The Compare Lines command enables you to select original line data and compare it to an imported file to find linework that does not have an identical match. This is useful when receiving revisions of data, to be able to find w... | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Inspect Line Nodes | `ANZ_InspectLineNodes` / 29885 | The Inspect Line Nodes command enables you to select a line and report the elevation, chainage, azimuth, and grades for all the nodes along the line. Annotate results to a text layer and create an Excel report. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Check Deflections | `ANZ_CheckLineDeflections` / 29719 | The Check Line Deflections command enables you to search selected lines to find and highlight nodes that exceed a chosen deflection angle. Use this command to find string errors before sending data to the field, or to display d... | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |

### Divide Area

| tool | key / help | what it does | opens |
|---|---|---|---|
| Adjust Area | `ANZ_AdjustArea` / 29661 | The Adjust Area command enables you to place a new line or polygon that creates a boundary area equal to a value specified. It requires a selection of at least three source lines and a reference line to calculate. | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
| Divide Area | `DivideArea` / 27507 | Use the Divide Area command to divide the area in a linestring-based polygonal feature into subareas based on any of the following criteria: | panel: Area to Divide [text], Origin [text], End point [text], Divide area based on [choice], Amount [min. 2] [text]. Buttons: Divide, Close |

### Advanced

| tool | key / help | what it does | opens |
|---|---|---|---|
| Composite Geometry | `CreateCompositeGeometry` / 28033 | Use the Create Composite Geometry command to combine simpler geometry objects, such as lines and/or polygons, into a single multipart geometric object used to represent complex spatial features, including objects with "holes" t... | panel: Name [text], Composite type [choice], Color [choice], Layer [choice], Elements to add to composite [text]. Buttons: Ok, Cancel, Options, Add, Remove |
| Track Region | `TrackRegionOutline` / 7389 | Use the Track Region Outline command to create a 2D or 3D linestring representing the 2D outline of a region from a set of separate (potentially unconnected) lines and/or surface and site improvement edges. The region is derive... | panel: Layer [choice], Name [text], Merge holes to boundary [bool], Gap closure tolerance [text], Track interior regions [bool], Reference point [text], Lines [text]. Buttons: Close, Apply |
| Detect Crossing Geometry | `CrossingGeometry` / 23314 | Use the Detect Crossing Geometry command to identify where lines cross planimetrically (same X and Y coordinate, but at potentially different Z levels, including self-intersecting geometry) and generate a list of the crossings.... | panel: Selection [text], Vertical tolerance (optional) [text], Exclude objects with undefined or 0 elevations [bool]. Buttons: Close, Apply, Report, Remove All Flags |
| Create XLines | `ANZ_CreateXLines` / 29796 | The Create X Lines command enables you to select a control line and create perpendicular lines at nominated intervals and user defined locations. Nominate the width of the X line either side of the control line, or use secondar... | not licensed (needs one of ['ANZToolbox', 'SurveyAdvancedJapan']) |
