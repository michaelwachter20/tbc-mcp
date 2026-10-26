# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Live usage tests for the Drafting tab on throwaway objects (layer MCP_DRTEST). py -3.12 drafting_tests.py [names]
Reference locations are numeric points (user preference) typed as point IDs into TBC's coordinate boxes.
Never prints, never fills personal details (3D PDF contact boxes stay empty).

Needs TBC
    Yes: TBC 2026.10 with a project open (use a copy) and the MCP Bridge macro on; talks to TBC at import
    time. Uses tests\\tbc_testkit.py.

How to run
    cd tests
    py -3.12 drafting_tests.py                         all tests in TESTS
    py -3.12 drafting_tests.py text edit_text          only these (function names without "t_"); some tests
                                                       depend on earlier ones (edit_text on text, insert_block
                                                       on create_block, purge_blocks on insert_block)
    Add --keep (alone or with test names) to skip the teardown. Run it from any folder.
    MANUAL tests (Angular Dimension, Insert Image) are never run by this script.

What it creates and cleans up
    Layer MCP_DRTEST, 3000 east / 600 north of the Plan View centre, with reference points A-D (100 x 50
    rectangle), M, T, L, U and per-test lines, polygons, text, dimensions, labels, label tables, a hatch, a
    block reference and a surface MCP_DR_SURF. Objects that don't sit on the layer (plotbox setup, plan set,
    sheet set, dynaview boundary set, scale bar, label tables, quick profile) are collected in MADE and deleted
    by cleanup_made(). Block definitions MCP_TEST_BLOCK and MCP_IMPORT_* are removed with a narrowed Purge
    Blocks (purge_only / t_purge_blocks), with Undo if more than expected disappeared. Temp files:
    tests\\mcp_blocks_tmp\\ (removed), tests\\mcp_test_3d.pdf (removed if TBC lets go of it).
    Settings are put back: Labeling Scale Factor's previous option and factor, and Import Blocks' 'My block
    folder path' as it was before the test. The Insert Image test (manual only) deletes its tests\\mcp_test_image.bmp.

What it writes
    tests\\drafting_results.json ({"results": [...]}, git-ignored).

Pass / fail
    Mostly "the expected new object exists" (by type and name), checked by listing the layer or walking the
    project (find_types, snap), plus property read-backs (props) and panel status texts such as
    "labeled: 2". "N/M passed" at the end; FAILs don't change the exit code.
"""
import json, math, os, sys
from tbc_testkit import S, record, close, base, points, entities, make_points, make_line, open_cmd, fill, click, cleanup, run, done

LAYER = "MCP_DRTEST"
E0, N0 = base(3000, 600)
P = {}  # alias -> point ID
SER = {}  # alias -> point serial
# windows already open before the run; cleanup() closes any other non-modal window left behind
BASE_FORMS = set(f["id"] for f in S.run_ipy("command_ui", "forms", {}))

# IronPython run inside TBC with args = serial and names = [property names]: returns the object's type and
# str() of every listed property it has (missing ones are skipped). Several candidate names are passed because
# the property holding e.g. a text's string isn't the same on every drafting type.
PROPS = r"""
o = bridge.lookup(prj, args)
out = {'type': o.GetType().FullName}
for n in names:
    try:
        v = getattr(o, n)
        out[n] = str(v)
    except Exception:
        pass
result = out
"""


def props(serial, names):
    """{"type": full .NET type name, <name>: str(value) for each of `names` the object has} (see PROPS)."""
    return S.call_bridge("execute_python", {"code": "args = %d\nnames = %r\n" % (serial, names) + PROPS, "transaction": False})["result"]


def setup():
    """Create the layer and reference points (z 10), offsets from (E0, N0): A (0,0), B (100,0), C (100,50),
    D (0,50), M (50,25) centre, T (50,80) above for text/leaders, L (50,-20) below for the dimension line,
    U (120,60) for tables and block inserts."""
    S.call_bridge("create_layer", {"name": LAYER})
    coords = {"A": (0, 0, 10), "B": (100, 0, 10), "C": (100, 50, 10), "D": (0, 50, 10), "M": (50, 25, 10),
              "T": (50, 80, 10), "L": (50, -20, 10), "U": (120, 60, 10)}
    made = make_points(LAYER, [(E0 + x, N0 + y, z) for x, y, z in coords.values()])
    for k, p in zip(coords, made):
        P[k] = p["name"]
        SER[k] = p["serial"]
    print("test area E %.2f N %.2f; reference points %s" % (E0, N0, P))


def ents_before():
    """Serials of everything on the test layer now."""
    return set(e["serial"] for e in entities(LAYER))


def new_objects(before):
    """Non-point objects on the test layer that weren't in `before`."""
    return [e for e in entities(LAYER) if e["serial"] not in before and not e["type"].endswith("Point")]


def panel_texts():
    """The static texts of the open panel (status lines such as "Points labeled: 2")."""
    return S.run_ipy("command_ui", "state", {"include_text": True}).get("texts")


def ln(name, pts, closed=False):
    """Throwaway linestring on the test layer through (x, y) offsets from (E0, N0), z 10."""
    return make_line(LAYER, name, [(E0 + x, N0 + y, 10) for x, y in pts], closed=closed)


# ---------------------------------------------------------------- text
# serial of the text made by t_text, edited by t_edit_text
TEXT = {}


# Create Text (createtext) at point T, height 2, "Middle center", content typed into the rich text box: one new
# object whose text property contains "MCP TEST TEXT".
def t_text():
    b = ents_before()
    open_cmd("createtext")
    r = fill([["Layer", LAYER], ["Height", "2"], ["Justification", "Middle center"],
              ["TextInsertionPointCoordinateEdit", P["T"]], ["richTextBox1", "MCP TEST TEXT"]], press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    pr = props(new[0]["serial"], ["Text", "TextString", "Contents", "Height", "Position", "InsertionPoint", "Location"]) if new else {}
    if new:
        TEXT["serial"] = new[0]["serial"]
    ok = len(new) == 1 and any("MCP TEST TEXT" in str(v) for v in pr.values())
    record("Create Text", ok, "%s %s" % ([x["type"] for x in new], pr), r)


# Edit Text (edittext) on t_text's text: the panel's richTextBox* field is found by id, set to "MCP EDITED"
# and applied; the text property must now contain it. The panel's fields are printed as diagnostics.
def t_edit_text():
    if "serial" not in TEXT:
        record("Edit Text", False, "needs the text from Create Text")
        return
    open_cmd("edittext", select=[TEXT["serial"]])
    st = S.run_ipy("command_ui", "state", {})
    print("      edit text fields:", [(f["id"], f.get("label"), f.get("value")) for f in st["fields"]], [b.get("text") for b in st["buttons"]])
    box = [f["id"] for f in st["fields"] if f["id"].lower().startswith("richtextbox")]
    r = fill([[box[0], "MCP EDITED"]], press="Apply", wait=2) if box else {"error": "no text box"}
    S.run_ipy("command_ui", "close", {})
    pr = props(TEXT["serial"], ["Text", "TextString", "Contents"])
    ok = any("MCP EDITED" in str(v) for v in pr.values())
    record("Edit Text", ok, "text now %s" % pr, r)


# ---------------------------------------------------------------- dimensions
# Linear Dimension (createlineardimension), "Two points" A and B, dimension line through L: exactly one new
# Dimension object (TBC also adds an MText for its text). Candidate value properties are reported.
def t_linear_dimension():
    b = ents_before()
    open_cmd("createlineardimension")
    r = fill([["Layer", LAYER], ["Two points", True], ["Point1CoordinateEdit", P["A"]], ["Point2CoordinateEdit", P["B"]],
              ["LocationPointCoordinateEdit", P["L"]]], press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    dims = [x for x in new if "Dimension" in x["type"]]
    pr = props(dims[0]["serial"], ["Measurement", "DimensionValue", "MeasuredValue", "Text", "DimensionText", "TextOverride"]) if dims else {}
    ok = len(dims) == 1
    record("Linear Dimension", ok, "%s %s (A-B = 100; TBC also adds an MText for the dimension text)" % ([x["type"] for x in new], pr), r)


# Angular Dimension (createangulardimension), "Two line segments" A-B and A-D, location M: one new Dimension
# (90 degrees). In MANUAL, not run (see the note above MANUAL).
def t_angular_dimension():
    # "Arc segment" mode linked by serial says "A valid segment cannot be obtained from the selected object" (it
    # needs a pick). "Two line segments" with two single-segment lines leaves nothing to pick: A-B and A-D = 90 deg.
    l1 = ln("DR_ANG1", [(0, 0), (100, 0)])
    l2 = ln("DR_ANG2", [(0, 0), (0, 50)])
    b = ents_before()
    open_cmd("createangulardimension")
    r = fill([["Layer", LAYER], ["Two line segments", True], ["Line1SelectEntity", l1], ["Line2SelectEntity", l2],
              ["LocationPointCoordinateEdit", P["M"]]], press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    dims = [x for x in new if "Dimension" in x["type"]]
    pr = props(dims[0]["serial"], ["Measurement", "Angle", "MeasuredValue", "Text", "DimensionText"]) if dims else {}
    ok = len(dims) == 1
    record("Angular Dimension", ok, "%s %s (A-B vs A-D = 90 deg)" % ([x["type"] for x in new], pr), r)


# ---------------------------------------------------------------- labels
# Label Points (labelpoints) for A and B (Selection box takes serials) -> Add: the panel must report
# "labeled: 2".
def t_label_points():
    b = ents_before()
    open_cmd("labelpoints")
    r = fill([["Layer", LAYER], ["Selection", [SER["A"], SER["B"]]]], press="Add", wait=2)
    tx = panel_texts()
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    ok = any("labeled: 2" in str(t) for t in tx)
    record("Label Points", ok, "panel %s; new objects %s" % (tx, [x["type"] for x in new]), r)


# Label Lines (labellines) on a two-segment line: passes when new objects appear on the layer or a panel
# status line mentioning "label" contains a 1. A loose check: the detail line shows what TBC reported.
def t_label_lines():
    line = ln("DR_LBL_LINE", [(0, 0), (100, 0), (100, 50)])
    b = ents_before()
    open_cmd("labellines")
    st = S.run_ipy("command_ui", "state", {})
    # the multi-select box is the field showing "Selected: n"; its id is looked up rather than hard-coded
    ms = [f["id"] for f in st["fields"] if "Selected:" in str(f.get("value"))]
    r = fill([["Layer", LAYER], [ms[0], [line]]], press="Add", wait=2)
    tx = panel_texts()
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    ok = bool(new) or any("1" in str(t) for t in tx if "label" in str(t).lower())
    record("Label Lines", ok, "panel %s; new objects %s" % (tx, [x["type"] for x in new]), r)


def make_polygon(name, keys=("A", "B", "C", "D")):
    """Create Polygon -> Edit Linestring (Point ID + Save per vertex). The serial shown in Edit Linestring's 'Line'
    box is REPLACED once vertices are saved (polygons only), so look the polygon up by name afterwards.

    keys are aliases from P; returns the polygon's serial.
    """
    open_cmd("createpolygon")
    fill([["Name", name], ["Layer", LAYER]], press="OK", wait=2)
    fill([["LocationTypeComboBox", "Point ID"]])
    for k in keys:
        fill([["Point ID", P[k]]])
        click("Save", wait=1.2)
    click("Close", wait=1.5)
    S.pace_command()
    return [e["serial"] for e in entities(LAYER) if e.get("name") == name and "Polygon" in e["type"]][0]


# Label Polygons (labelpolygons) on polygon A-B-C-D: same loose check as Label Lines.
def t_label_polygons():
    poly = make_polygon("DR_PG")
    b = ents_before()
    open_cmd("labelpolygons")
    st = S.run_ipy("command_ui", "state", {})
    ms = [f["id"] for f in st["fields"] if "Selected:" in str(f.get("value"))]
    r = fill([["Layer", LAYER], [ms[0], [poly]]], press="Add", wait=2)
    tx = panel_texts()
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    ok = bool(new) or any("1" in str(t) for t in tx if "label" in str(t).lower())
    record("Label Polygons", ok, "panel %s; new objects %s" % (tx, [x["type"] for x in new]), r)


# "points" -> serials of the point labels made by label_points_now (reused by t_leader_lines)
LABELS = {}


def label_points_now():
    """Label points A and B with Label Points and return the new PointLabel serials."""
    b = ents_before()
    open_cmd("labelpoints")
    fill([["Layer", LAYER], ["Selection", [SER["A"], SER["B"]]]], press="Add", wait=2)
    S.run_ipy("command_ui", "close", {})
    LABELS["points"] = [e["serial"] for e in new_objects(b) if "PointLabel" in e["type"]]
    S.pace_command()
    return LABELS["points"]


# Point Label Table (createpointlabeltable) after labelling A and B: exactly one new Table object on the layer.
# Row-count candidate properties are reported, not checked.
def t_point_label_table_rows():
    labels = label_points_now()
    b = ents_before()
    open_cmd("createpointlabeltable")
    r = fill([["Layer", LAYER], ["Title", "MCP POINT TABLE"], ["LocationCoordinateEdit", P["U"]]], press="OK", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = [e for e in new_objects(b) if "Table" in e["type"]]
    pr = props(new[0]["serial"], ["RowCount", "Rows", "Title", "EntryCount", "Count"]) if new else {}
    ok = len(new) == 1
    record("Point Label Table", ok, "%d point labels -> %s %s" % (len(labels), [e["type"] for e in new], pr), r)


# Leader Lines (createleaderlines) from a point label (selTarget, by serial) to point T: passes when new
# objects appear or one of the label's Leader* properties is set.
def t_leader_lines():
    labels = LABELS.get("points") or label_points_now()
    b = ents_before()
    open_cmd("createleaderlines")
    r = fill([["selTarget", labels[0]], ["cdeInsertionPoint", P["T"]]], press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    pr = props(labels[0], ["LeaderType", "HasLeader", "Leader", "LabelPosition", "InsertionPoint"])
    ok = bool(new) or any(v not in ("None", "", "False") for k, v in pr.items() if "Leader" in k)
    record("Leader Lines", ok, "new %s; label now %s" % ([e["type"] for e in new], pr), r)


# ---------------------------------------------------------------- blocks
BLOCK = "MCP_TEST_BLOCK"

# IronPython run inside TBC with mode and keep defined first: finds the Purge Blocks panel's WinForms
# 'listView1' (walking the open command panel's controls) and lists its block definitions. mode 'only' ticks
# exactly the names in `keep` and unticks everything else; any other mode ('read') only reads. Returns the
# list size, what is ticked, and which of `keep` are present.
LISTVIEW = r"""
ui = TrimbleOffice.TheOffice.MainForm.CommandHost.TopCommand.CommandUI
def find(c, n):
    if c.Name == n: return c
    for k in c.Controls:
        r = find(k, n)
        if r is not None: return r
lv = find(ui, 'listView1')
names = [str(i.Text) for i in lv.Items]
keeps = keep if isinstance(keep, list) else [keep]
if mode == 'only':
    for i in lv.Items:
        want = str(i.Text) in keeps
        if bool(i.Checked) != want:
            i.Checked = want
result = {'count': lv.Items.Count, 'checked': [str(i.Text) for i in lv.Items if i.Checked],
          'has_keep': all(k in names for k in keeps), 'present': [k for k in keeps if k in names]}
"""


def purge_list(mode, keep=BLOCK):
    """Read ('read') or narrow ('only') the open Purge Blocks list; see LISTVIEW."""
    return S.call_bridge("execute_python", {"code": "mode = %r\nkeep = %r\n" % (mode, keep) + LISTVIEW, "transaction": False})["result"]


def purge_only(names):
    """Purge exactly these unreferenced block definitions (everything else unticked first); undo if more went.

    Safety steps: refuse (and close) unless the ticked set equals the names present; after Apply, reopen the
    panel and compare list sizes; if more definitions disappeared than were asked for, run Undo.
    Returns {"purged": bool, ...} with the reason when nothing was purged.
    """
    open_cmd("purgeblocks")
    before = purge_list("read", names)
    sel = purge_list("only", names)
    if not before["present"] or sorted(sel["checked"]) != sorted(before["present"]):
        S.run_ipy("command_ui", "close", {})
        return {"purged": False, "why": "selection %s != %s" % (sel["checked"][:5], before["present"])}
    click("Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    S.pace_command()
    open_cmd("purgeblocks")
    after = purge_list("read", names)
    S.run_ipy("command_ui", "close", {})
    lost = before["count"] - after["count"]
    if lost > len(before["present"]):
        S.t_run_command({"key": "undo"})
        return {"purged": False, "why": "%d definitions disappeared, undo run" % lost}
    return {"purged": not after["present"], "lost": lost, "names": before["present"]}


# temp folder for the generated block DXF (in .gitignore; removed by t_import_blocks)
BLOCKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_blocks_tmp")
# IronPython run inside TBC with `name` defined first: in the Import Blocks panel's 'treeView1' (files -> blocks),
# tick every second-level node whose text equals `name` and return "<parent>/<node>" for each one ticked.
TREE = r"""
ui = TrimbleOffice.TheOffice.MainForm.CommandHost.TopCommand.CommandUI
def find(c, n):
    if c.Name == n: return c
    for k in c.Controls:
        r = find(k, n)
        if r is not None: return r
tv = find(ui, 'treeView1')
hit = []
for top in tv.Nodes:
    for n in top.Nodes:
        if str(n.Text) == name:
            n.Checked = True
            hit.append(str(top.Text) + '/' + str(n.Text))
result = hit
"""


# Import Blocks (importblocks): writes a minimal DXF (R12, AC1009) holding one block MCP_IMPORT_BLOCK (a single
# 10-unit line), points the panel's folder box at BLOCKS_DIR, ticks the file's node and imports. Passes when
# the node was ticked and a new block definition MCP_IMPORT_BLOCK exists. Afterwards the MCP_IMPORT* definitions
# are purged and the folder setting is cleared again. Runs last in TESTS.
def t_import_blocks():
    import os, shutil
    os.makedirs(BLOCKS_DIR, exist_ok=True)
    # DXF group-code/value pairs, one per line: HEADER, a BLOCKS section with the block, an empty ENTITIES section
    dxf = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "0", "ENDSEC", "0", "SECTION", "2", "BLOCKS",
           "0", "BLOCK", "8", "0", "2", "MCP_IMPORT_BLOCK", "70", "0", "10", "0.0", "20", "0.0", "30", "0.0", "3", "MCP_IMPORT_BLOCK",
           "0", "LINE", "8", "0", "10", "0.0", "20", "0.0", "30", "0.0", "11", "10.0", "21", "0.0", "31", "0.0",
           "0", "ENDBLK", "8", "0", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES", "0", "ENDSEC", "0", "EOF"]
    with open(os.path.join(BLOCKS_DIR, "MCP_IMPORT_TEST.dxf"), "w") as f:
        f.write("\n".join(dxf) + "\n")
    defs0 = set(x["name"] for x in find_types(["BlockView"]))
    open_cmd("importblocks")
    # the user's 'My block folder path' setting, put back at the end
    folder0 = next((f.get("value") or "" for f in S.run_ipy("command_ui", "state", {}).get("fields", [])
                    if f.get("id") == "browseFile1"), "")
    fill([["browseFile1", BLOCKS_DIR]])
    hit = S.call_bridge("execute_python", {"code": "name = 'MCP_IMPORT_TEST'\n" + TREE, "transaction": False})["result"]
    r = click("Import", wait=3)
    S.run_ipy("command_ui", "close", {})
    new = sorted(set(x["name"] for x in find_types(["BlockView"])) - defs0)
    ok = bool(hit) and "MCP_IMPORT_BLOCK" in new
    record("Import Blocks", ok, "ticked %s -> new definitions %s (TBC adds a file-level block too)" % (hit, new), r)
    S.pace_command()
    # remove every new definition starting MCP_IMPORT (the block and the file-level one)
    pr = purge_only([n for n in new if n.startswith("MCP_IMPORT")])
    print("      purge of the imported test blocks:", pr)
    # put the user's 'My block folder path' setting back as it was and remove the test file
    S.pace_command()
    open_cmd("importblocks")
    fill([["browseFile1", folder0]])
    S.run_ipy("command_ui", "close", {})
    shutil.rmtree(BLOCKS_DIR, ignore_errors=True)


# Polygon Label Table (createpolygonlabeltable): label a polygon, create the table at U, and if TBC opens
# Edit Label Table add the polygon there. Passes when a new LabelTable exists and the panel reports
# "polygons: 1". The table is added to MADE (label tables are found by walking the project).
def t_polygon_label_table():
    poly = make_polygon("DR_PG_TBL")
    # a label table lists LABELED objects: label the polygon first (as for lines)
    open_cmd("labelpolygons")
    st = S.run_ipy("command_ui", "state", {})
    ms = [f["id"] for f in st["fields"] if "Selected:" in str(f.get("value"))]
    fill([["Layer", LAYER], [ms[0], [poly]]], press="Add", wait=2)
    S.run_ipy("command_ui", "close", {})
    S.pace_command()
    tb0 = set(x["serial"] for x in find_types(["LabelTable"]))
    open_cmd("createpolygonlabeltable")
    r = fill([["Layer", LAYER], ["Title", "MCP POLYGON TABLE"], ["LocationCoordinateEdit", P["U"]]], press="OK", wait=2)
    st = S.run_ipy("command_ui", "state", {})
    if st.get("open_command") == "EditLabelTable":
        ms = [f["id"] for f in st["fields"] if "Selected:" in str(f.get("value"))]
        r = fill([[ms[0], [poly]]], press="Add", wait=2)
    tx = panel_texts()
    S.run_ipy("command_ui", "close", {})
    new = [x for x in find_types(["LabelTable"]) if x["serial"] not in tb0]
    MADE.extend(x["serial"] for x in new)
    record("Polygon Label Table", len(new) >= 1 and any("polygons: 1" in str(t) for t in tx), "%s; panel %s" % (new[:1], tx), r)


# Create Block (createblock) MCP_TEST_BLOCK from two lines, base point A: exactly one block definition with
# that name exists afterwards. Reports how many source lines are left.
def t_create_block():
    l1 = ln("DR_BLK1", [(0, -60), (20, -60)])
    l2 = ln("DR_BLK2", [(20, -60), (20, -45)])
    b = ents_before()
    open_cmd("createblock")
    r = fill([["memberSelection1", [l1, l2]], ["BlockName", BLOCK], ["coordinateEdit1", P["A"]]], press="Create", wait=2)
    S.run_ipy("command_ui", "close", {})
    left = [e for e in entities(LAYER) if e["serial"] in (l1, l2)]
    new = new_objects(b)
    # the definition is a BlockView (not on a layer); the Insert Block list only shows a sample of its 700+ names
    defs = [x for x in find_types(["BlockView"]) if x["name"] == BLOCK]
    ok = len(defs) == 1
    record("Create Block", ok, "definition %s; source lines left %d; new objects %s" % (defs, len(left), [e["type"] for e in new]), r)


# Insert Block (insertblock) of MCP_TEST_BLOCK at U on the test layer, rotation 0: one new BlockReference whose
# block-name property mentions MCP_TEST_BLOCK. Needs t_create_block.
def t_insert_block():
    b = ents_before()
    open_cmd("insertblock")
    r = fill([["blkComboBox1", BLOCK], ["layer1", LAYER], ["Location1", P["U"]], ["Rotation", "0"]], press="Insert", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    pr = props(new[0]["serial"], ["BlockName", "Name", "BlockViewName", "Block"]) if new else {}
    ok = len(new) == 1 and "BlockReference" in new[0]["type"] and any(BLOCK in str(v) for v in pr.values())
    record("Insert Block", ok, "%s %s" % ([e["type"] for e in new], pr), r)


# Purge Blocks (purgeblocks) narrowed to MCP_TEST_BLOCK: its references on the layer are deleted first (TBC's
# Delete command), the list is narrowed to just that block, then Apply. Passes when the block is gone and the
# list shrank by exactly one; if more than one went, Undo is run.
def t_purge_blocks():
    # only ever purge our own test block: delete its references first, untick everything else, verify, Apply
    refs = [e["serial"] for e in entities(LAYER) if "BlockReference" in e["type"]]
    if refs:
        S.t_delete_entities({"serials": refs})
        S.pace_command()
    open_cmd("purgeblocks")
    before = purge_list("read")
    if not before["has_keep"]:
        S.run_ipy("command_ui", "close", {})
        record("Purge Blocks", False, "%s not in the purge list (still referenced?) - nothing purged" % BLOCK)
        return
    sel = purge_list("only")
    if sel["checked"] != [BLOCK]:
        S.run_ipy("command_ui", "close", {})
        record("Purge Blocks", False, "could not narrow the selection to the test block (%s) - NOT applied" % sel["checked"][:5])
        return
    r = click("Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    S.pace_command()
    open_cmd("purgeblocks")
    after = purge_list("read")
    S.run_ipy("command_ui", "close", {})
    lost = before["count"] - after["count"]
    ok = not after["has_keep"] and lost == 1
    if lost > 1:
        S.t_run_command({"key": "undo"})
        print("      !!! more than one block definition disappeared (%d): undo run" % lost)
    record("Purge Blocks", ok, "list %d -> %d entries; test block gone: %s" % (before["count"], after["count"], not after["has_keep"]), r)


# ---------------------------------------------------------------- hatch, print, plan sets, 3D PDF
# Create Hatch (createhatch), CROSS pattern at scale 1 inside a closed 100 x 50 line: a new object whose type
# contains "atch" (Hatch / hatch).
def t_hatch():
    rect = ln("DR_HATCH_BND", [(0, 0), (100, 0), (100, 50), (0, 50), (0, 0)], closed=True)
    b = ents_before()
    open_cmd("createhatch")
    r = fill([["m_SelectedEntities", [rect]], ["m_oLayerControl", LAYER], ["cb_Patterns", "CROSS"], ["ne_Scale", "1"]], press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    ok = len(new) >= 1 and any("atch" in e["type"] for e in new)
    record("Create Hatch", ok, "%s" % [e["type"] for e in new], r)


# IronPython run inside TBC with `words` defined first: walk the project's containers up to 3 levels deep and
# list (max 200) objects whose .NET type name contains any of `words`, with serial, full type and name.
# Used for objects that aren't listed on a layer (block definitions, sheet sets, label tables ...).
FIND_TYPES = r"""
out = []
def walk(c, d=0):
    for o in c:
        t = o.GetType().Name
        if any(w in t for w in words):
            out.append({'serial': int(o.SerialNumber), 'type': o.GetType().FullName, 'name': str(getattr(o, 'Name', '') or '')})
        if d < 3 and hasattr(o, 'GetEnumerator') and not isinstance(o, str):
            try: walk(o, d + 1)
            except Exception: pass
walk(prj)
result = out[:200]
"""


def find_types(words):
    """Objects anywhere in the project whose type name contains one of `words` (see FIND_TYPES)."""
    return S.call_bridge("execute_python", {"code": "words = %r\n" % words + FIND_TYPES, "transaction": False})["result"]


MADE = []  # non-layer objects to delete at the end (plan sets, plotboxes)


# the three object types Print Plan View's Create makes (see t_print_plan_view_create)
PLOT_TYPES = ["DynaviewBoundaryCollection", "PlanGridSheetSet", "Boundary"]


# Print Plan View (printplanview) -> Create (never Print) a plotbox MCP_PLOTBOX at scale 50 centred on the test
# rectangle: all three PLOT_TYPES appear with that name. They go to MADE for deletion.
def t_print_plan_view_create():
    # Create (never Print) makes a printable setup named after the plotbox: DynaviewBoundaryCollection + its
    # Boundary + PlanGridSheetSet (+ BasicSheet, DynaViews). Deleting the first three removes all of it.
    before = set(x["serial"] for x in find_types(PLOT_TYPES))
    open_cmd("printplanview")
    # Location (plotbox centre) is sometimes pre-filled from the view and sometimes '?': Create silently does
    # nothing without it. A point ID in this WPF box worked only 1 time in 3; typed 'northing, easting' always works
    r = fill([["Name", "MCP_PLOTBOX"], ["Scale", "50"], ["Location", "%.3f, %.3f" % (N0 + 25, E0 + 50)]], wait=1)
    st = S.run_ipy("command_ui", "state", {})
    if st.get("open_command") == "PrintPlanView":
        r = click("Create", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = [x for x in find_types(PLOT_TYPES) if x["serial"] not in before and x["name"] == "MCP_PLOTBOX"]
    MADE.extend(x["serial"] for x in new)
    ok = set(x["type"].split(".")[-1] for x in new) == set(PLOT_TYPES)  # the walk can meet the boundary twice
    record("Print Plan View (Create plotbox)", ok, "%s (nothing was printed)" % [(x["type"].split(".")[-1], x["name"]) for x in new], r)


# Create Plan Set (createplanset) MCP_TEST_PLANSET: a new PlanSet/SheetSet object with that name (added to MADE).
def t_plan_set():
    before = set(x["serial"] for x in find_types(["PlanSet", "SheetSet"]))
    open_cmd("createplanset")
    r = fill([["NameTextBox", "MCP_TEST_PLANSET"]], press="OK", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = [x for x in find_types(["PlanSet", "SheetSet"]) if x["serial"] not in before]
    MADE.extend(x["serial"] for x in new)
    ok = any(x["name"] == "MCP_TEST_PLANSET" for x in new)
    record("Create Plan Set", ok, "%s" % new, r)


# 3D PDF output file inside tests\ (tests/*.pdf is in .gitignore)
PDF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_test_3d.pdf")


# Create 3D PDF (create3dpdf) to PDF with "ModifyProjectSettings" off: the file exists and is over 1000 bytes.
# The file is then deleted (if TBC still holds it, the next run's first step deletes it).
def t_create_3d_pdf():
    import os
    if os.path.exists(PDF):
        os.remove(PDF)
    open_cmd("create3dpdf")
    # output inside the testing area; contact boxes (name, phone, email, company, website) left EMPTY on purpose
    r = fill([["m_OutputFile", PDF], ["ModifyProjectSettings", False]], press="OK", wait=5)
    S.wait_idle()
    S.run_ipy("command_ui", "close", {})
    size = os.path.getsize(PDF) if os.path.exists(PDF) else 0
    ok = size > 1000
    record("Create 3D PDF", ok, "file %s bytes" % size, r)
    try:
        os.remove(PDF)  # TBC can keep the new file open for a while; then it is removed on the next run
    except OSError:
        pass


def coord(x, y):
    """'northing, easting' text for WPF coordinate boxes that do not resolve point IDs reliably."""
    return "%.3f, %.3f" % (N0 + y, E0 + x)


# Line Label Table (createlinelabeltable): label a line, create the table at U, add the line in the Edit Label
# Table panel that OK opens. Passes when a new Table is on the layer or a new LabelTable exists anywhere
# (those not on the layer go to MADE).
def t_line_label_table():
    line = ln("DR_TBL_LINE", [(0, 0), (100, 0)])
    open_cmd("labellines")
    st = S.run_ipy("command_ui", "state", {})
    ms = [f["id"] for f in st["fields"] if "Selected:" in str(f.get("value"))]
    fill([["Layer", LAYER], [ms[0], [line]]], press="Add", wait=2)
    S.run_ipy("command_ui", "close", {})
    S.pace_command()
    b = ents_before()
    tb0 = set(x["serial"] for x in find_types(["LabelTable"]))
    open_cmd("createlinelabeltable")
    r = fill([["Layer", LAYER], ["Title", "MCP LINE TABLE"], ["LocationCoordinateEdit", P["U"]]], press="OK", wait=2)
    # OK opens 'Edit Label Table': add the segments there (Multi-select lines + Add), then Close
    r = fill([["memberSelection", [line]]], press="Add", wait=2)
    tx = panel_texts()
    S.run_ipy("command_ui", "close", {})
    new = [e for e in new_objects(b) if "Table" in e["type"]]
    anywhere = [x for x in find_types(["LabelTable"]) if x["serial"] not in tb0]
    MADE.extend(x["serial"] for x in anywhere if x["serial"] not in [e["serial"] for e in new])
    record("Line Label Table", len(new) == 1 or len(anywhere) >= 1,
           "on layer %s; anywhere %s; edit panel %s" % ([e["type"] for e in new], anywhere, tx), r)


# Labeling Scale Factor (planarscalefactor): "Use a fixed scale factor" 1.0 -> Apply; the panel's scale factor
# text must show 1.0 afterwards. This is a project setting, so the panel's previous choices are put back after.
def t_labeling_scale_factor():
    open_cmd("planarscalefactor")
    before = panel_texts()
    # remember the selected option(s) and the factor box, to restore them afterwards
    orig = [f for f in S.run_ipy("command_ui", "state", {}).get("fields", [])
            if (f.get("kind") == "radio" and f.get("value") is True) or f.get("id") == "scaleFactorTextBox"]
    r = fill([["Use a fixed scale factor", True], ["scaleFactorTextBox", "1.0"]], press="Apply", wait=2)
    after = panel_texts()
    S.run_ipy("command_ui", "close", {})
    ok = any("1.0" in str(t) for t in after if "scale factor" in str(t).lower())
    record("Labeling Scale Factor", ok, "before %s; after %s (fixed factor 1.0 = no ground scaling)" % (before[:1], after[:1]), r)
    # put the project setting back: the factor text first (it only applies to the fixed option), then the option
    # that was selected before
    back = [[f["id"], f.get("value") or ""] for f in orig if f.get("kind") != "radio"] + \
           [[f["id"], True] for f in orig if f.get("kind") == "radio"]
    if back:
        S.pace_command()
        open_cmd("planarscalefactor")
        try:
            print("      restored the labeling scale factor:", fill(back, press="Apply", wait=2).get("errors"))
        finally:
            S.run_ipy("command_ui", "close", {})


# Create Dynaview Boundary Set (createdynaviewboundarycollection) MCP_DVB_SET, 1 row x 2 columns, origin at the
# test origin (typed as "northing, easting"): a new collection with that name (added to MADE).
def t_dynaview_boundary_set():
    before = set(x["serial"] for x in find_types(["DynaviewBoundaryCollection"]))
    open_cmd("createdynaviewboundarycollection")
    r = fill([["txtName", "MCP_DVB_SET"], ["lyrLayer", LAYER], ["nudRows", 1], ["nudColumns", 2], ["crdOrigin", coord(0, 0)]], press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = [x for x in find_types(["DynaviewBoundaryCollection"]) if x["serial"] not in before]
    MADE.extend(x["serial"] for x in new)
    ok = any(x["name"] == "MCP_DVB_SET" for x in new)
    record("Dynaview Boundary Set", ok, "%s" % [(x["type"].split(".")[-1], x["name"]) for x in new], r)


# Create Sheet Set (createsheetset) MCP_TEST_SHEETSET, Standard, ISO A1 landscape: a new set with that name
# (added to MADE).
def t_sheet_set():
    before = set(x["serial"] for x in find_types(["SheetSet", "PlanSet"]))
    open_cmd("createsheetset")
    r = fill([["NameTextBox", "MCP_TEST_SHEETSET"], ["cbSheetSetTypePicker", "Standard"], ["cmbPaperSize", "ISO A1 (594 x 841 mm)"],
              ["selLandscape", True]], press="OK", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = [x for x in find_types(["SheetSet", "PlanSet"]) if x["serial"] not in before]
    MADE.extend(x["serial"] for x in new)
    ok = any(x["name"] == "MCP_TEST_SHEETSET" for x in new)
    record("Create Sheet Set", ok, "%s" % [(x["type"].split(".")[-1], x["name"]) for x in new], r)


# Create Scale Bar (createscalebar), specified scale 1:50, "Alternating Scale Bar", 80 below the test origin:
# at least one new ScaleBar object (found by type, added to MADE).
def t_scale_bar():
    b = ents_before()
    open_cmd("createscalebar")
    sb0 = set(x["serial"] for x in find_types(["ScaleBar"]))
    r = fill([["rdoSpecifyScale", True]])
    r = fill([["nedScale", "50"], ["cboBarType", "Alternating Scale Bar"], ["cboLayer", LAYER], ["cdeLocation", coord(0, -80)]], press="OK", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = [x for x in find_types(["ScaleBar"]) if x["serial"] not in sb0]  # Alignment.ScaleBar: not listed on a layer
    MADE.extend(x["serial"] for x in new)
    ok = len(new) >= 1
    record("Create Scale Bar", ok, "%s (specified scale 1:50)" % [x["type"] for x in new], r)


# image file for t_insert_image, written in tests\ (tests/*.bmp is in .gitignore) and deleted by the test
IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_test_image.bmp")


# Insert Image (insertimage) of a generated 4 x 4 BMP, lower corner 100 north of the origin, scale 1: at least
# one new object on the layer. In MANUAL, not run: the note above MANUAL says Apply creates nothing (the image
# is placed and sized with grips in the view).
def t_insert_image():
    import os, struct
    # tiny 4x4 24-bit BMP made here (no external file needed)
    # each pixel is the bytes 00 80 ff (BMP stores blue, green, red); rows are padded to a multiple of 4 bytes.
    # Header: 14-byte BITMAPFILEHEADER ("BM", file size, reserved, pixel offset 54) + 40-byte BITMAPINFOHEADER
    # (4 x 4, 1 plane, 24 bits, no compression, 2835 pixels per metre = 72 dpi)
    w = h = 4
    row = b"\x00\x80\xff" * w + b"\x00" * ((4 - (w * 3) % 4) % 4)
    pix = row * h
    hdr = b"BM" + struct.pack("<IHHI", 54 + len(pix), 0, 0, 54) + struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(pix), 2835, 2835, 0, 0)
    with open(IMG, "wb") as f:
        f.write(hdr + pix)
    b = ents_before()
    open_cmd("insertimage")
    r = fill([["folderBrowserBox", IMG], ["m_CornerOne", coord(0, 100)], ["m_Layer", LAYER], ["Scale1", "1"]], press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    ok = len(new) >= 1
    record("Insert Image", ok, "%s" % [e["type"] for e in new], r)
    try:
        os.remove(IMG)  # TBC may still hold the file; then it stays (git-ignored)
    except OSError:
        pass


# throwaway surface for t_quick_profile; deleted by name in the teardown
SURF = "MCP_DR_SURF"
# IronPython run inside TBC: {serial: "<full type> | <name>"} for every object reached by walking the project's
# containers up to 3 levels deep. Taken before and after a command to see everything it made.
SNAP = r"""
out = {}
def walk(c, d=0):
    for o in c:
        try: out[int(o.SerialNumber)] = o.GetType().FullName + ' | ' + str(getattr(o, 'Name', '') or '')
        except Exception: pass
        if d < 3 and hasattr(o, 'GetEnumerator') and not isinstance(o, str):
            try: walk(o, d + 1)
            except Exception: pass
walk(prj)
result = out
"""


def snap():
    """Snapshot of every object in the project (see SNAP); slow on big projects, hence the 300 s timeout."""
    return S.call_bridge("execute_python", {"code": SNAP, "transaction": False}, timeout=300)["result"]


# Quick Profile (createquickprofile) across a throwaway surface MCP_DR_SURF (made from A, B, C, D, M) from
# (0,25) to (100,25), named MCP_QPROFILE, placed 150 below the origin: a new object named MCP_QPROFILE appears
# in the project snapshot. The panel's WPF boxes have no labels, so they are filled by generated ids
# (ClientAreaTextBox, ClientAreaTextBox#2 ...). Note: snap() returns JSON, so its serial keys come back as
# strings, and the int() conversion for MADE happens here.
def t_quick_profile():
    # small throwaway surface from A, B, C, D, M
    open_cmd("surfacecreate", select=[SER[k] for k in ("A", "B", "C", "D", "M")])
    fill([["Name", SURF]], press="OK", wait=2)
    S.wait_idle()
    done()
    S.pace_command()
    a = snap()
    open_cmd("createquickprofile")
    r = fill([["createNew", True], ["ClientAreaTextBox", coord(0, 25)], ["ClientAreaTextBox#2", coord(100, 25)],
              ["ComboBox", SURF], ["ClientAreaTextBox#4", "MCP_QPROFILE"], ["ComboBox#5", LAYER],
              ["ClientAreaTextBox#5", coord(0, -150)]], press="OK", wait=3)
    S.wait_idle()
    done()
    new = {k: v for k, v in snap().items() if k not in a}
    MADE.extend(int(k) for k, v in new.items() if "MCP_QPROFILE" in v or "QuickProfile" in v)
    ok = any("MCP_QPROFILE" in v for v in new.values())
    record("Quick Profile", ok, "new objects %s" % list(new.values())[:8], r)


def cleanup_made():
    """Delete the collected non-layer test objects (MADE) with TBC's own Delete command; errors are printed."""
    print("cleanup: non-layer test objects", sorted(set(MADE)))
    if MADE:
        try:
            print("cleanup:", S.t_delete_entities({"serials": sorted(set(MADE))}))
        except S.BridgeError as ex:
            print("cleanup: could not delete", MADE, ex)


TESTS = [t_text, t_edit_text, t_linear_dimension, t_label_points, t_label_lines, t_label_polygons,
         t_point_label_table_rows, t_leader_lines, t_create_block, t_insert_block, t_purge_blocks, t_hatch,
         t_print_plan_view_create, t_plan_set, t_create_3d_pdf, t_line_label_table, t_labeling_scale_factor,
         t_dynaview_boundary_set, t_sheet_set, t_scale_bar, t_quick_profile, t_polygon_label_table, t_import_blocks]
# Needs picks in the Plan View (the segment is chosen by the pick location): both modes reply
# "A valid segment cannot be obtained from the selected object." when the line/arc is linked by serial.
# Insert Image: file accepted and validated, lower corner typed, Apply -> nothing created (placed/sized with grips
# in the view). Copy to Sheet / Create Dynaview / Custom Sheet need a Sheet View open.
MANUAL = [t_angular_dimension, t_insert_image]

if __name__ == "__main__":
    # teardown (unless --keep): delete the non-layer objects first, then the surface, the layer's contents,
    # the layer and leftover windows
    run(TESTS, sys.argv[1:], setup,
        lambda: None if "--keep" in sys.argv else (cleanup_made(), cleanup([LAYER], surface_names=[SURF], base_forms=BASE_FORMS)))
    __import__("tbc_testkit").save_results("drafting_results.json")
