# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Live usage tests for the Home tab Selection group: Select Points, Duplicate Points, Elevation, Observations,
Layer, Polygon, Similar, Advanced (Quick Select), Invert Selection, Select All. Selection only - nothing is changed.
Throwaway points/lines on layer MCP_SELTEST; each test checks exactly what ends up selected (get_selection).
py -3.12 selection_tests.py [names]

Needs TBC
    Yes: TBC 2026.10 with a project open and the MCP Bridge macro on; talks to TBC at import time.
    Several tools act on the whole project (duplicates, elevation, observations, invert, select all), so the
    checks only look at which of OUR objects ended up selected (see ours()). Uses tests\\tbc_testkit.py.

How to run
    cd tests
    py -3.12 selection_tests.py                        all tests in TESTS
    py -3.12 selection_tests.py select_by_polygon      only these (function names without "t_")
    Add --keep (together with test names: it also counts as a name) to skip the teardown.
    Run from tests\\ so selection_results.json lands where .gitignore expects it (current directory).

What it creates and cleans up
    Layer MCP_SELTEST, 3000 east / 2400 north of the Plan View centre, with four coded points made through
    the Create Point panel: A (0,0, z10, SELA), B (10,0, z20, SELB), C (40,0, z30, SELA) and D (0,0, z10,
    SELDUP, same position as A), a closed box around A, B and D, and a separate line. The teardown clears the
    selection and deletes the layer's contents, the layer and leftover windows. Nothing else is changed.

What it writes
    selection_results.json in the current directory ({"results": [...]}).

Pass / fail
    Each test compares the set of our objects in get_selection with the expected set. Select Observations
    always passes (it only reports how many total-station observations the project has). "N/M passed" at
    the end; FAILs don't change the exit code.
"""
import json, sys
from tbc_testkit import S, record, base, entities, make_points, make_line, open_cmd, fill, click, cleanup, run, done

LAYER = "MCP_SELTEST"
E0, N0 = base(3000, 2400)
# P: alias A-D -> point ID, SER: alias -> point serial, OBJ: "box"/"line" -> linestring serial
P, SER = {}, {}
OBJ = {}
# windows already open before the run; cleanup() closes any other non-modal window left behind
BASE_FORMS = set(f["id"] for f in S.run_ipy("command_ui", "forms", {}))


def setup():
    """Create the layer, points A-D (one at a time, paced like command launches) and the two linestrings."""
    S.call_bridge("create_layer", {"name": LAYER})
    pts = {"A": (0, 0, 10, "SELA"), "B": (10, 0, 20, "SELB"), "C": (40, 0, 30, "SELA"), "D": (0, 0, 10, "SELDUP")}
    for k, (x, y, z, code) in pts.items():
        p = make_points(LAYER, [(E0 + x, N0 + y, z)], code=code)[0]
        P[k], SER[k] = p["name"], p["serial"]
        # each coded point opens the Create Point panel, so keep the server's minimum gap between launches
        S.pace_command()
    # closed boundary around A, B, D (not C): x -5..15, y -5..5
    OBJ["box"] = make_line(LAYER, "MCP_SEL_BOX", [(E0 - 5, N0 - 5, 0), (E0 + 15, N0 - 5, 0), (E0 + 15, N0 + 5, 0), (E0 - 5, N0 + 5, 0), (E0 - 5, N0 - 5, 0)], closed=True)
    OBJ["line"] = make_line(LAYER, "MCP_SEL_LINE", [(E0, N0 + 20, 5), (E0 + 40, N0 + 20, 5)])
    print("test area E %.2f N %.2f; points %s; objects %s" % (E0, N0, P, OBJ))


def selected():
    """Serials of everything currently selected in TBC (get_selection, up to 100000)."""
    return set(e["serial"] for e in S.call_bridge("get_selection", {"limit": 100000})["entities"])


def ours(sel):
    """Which of OUR test objects are in a selection (the selection may also hold the user's own data)."""
    names = {v: k for k, v in SER.items()}
    names.update({v: k for k, v in OBJ.items()})
    return sorted(names[s] for s in sel if s in names)


def clear():
    """Empty TBC's selection."""
    S.call_bridge("set_selection", {"serials": []})


# Select Points (selectpoints) by layer (cboLayer) and feature code (txtFieldCode) SELA: exactly A and C.
def t_select_points():
    clear()
    open_cmd("selectpoints")
    r = fill([["cboLayer", LAYER], ["txtFieldCode", "SELA"]], press="OK", wait=2)
    sel = selected()
    ok = ours(sel) == ["A", "C"] and len(sel) == 2
    record("Select Points (layer + feature code)", ok, "selected %d: ours %s" % (len(sel), ours(sel)), r)


# Select Points by point ID (SelectedPointID box): only B among our objects.
def t_select_points_by_id():
    clear()
    open_cmd("selectpoints")
    r = fill([["SelectedPointID", P["B"]]], press="OK", wait=2)
    sel = selected()
    record("Select Points (point ID)", ours(sel) == ["B"], "selected %d: ours %s" % (len(sel), ours(sel)), r)


# Select Points with "Add to current selection" on, starting from {B}: code SELA adds A and C -> A, B, C.
def t_add_to_selection():
    S.call_bridge("set_selection", {"serials": [SER["B"]]})
    open_cmd("selectpoints", select=[SER["B"]])
    r = fill([["cboLayer", LAYER], ["txtFieldCode", "SELA"], ["chkAddToCurrentSelection", True]], press="OK", wait=2)
    sel = selected()
    record("Select Points (add to current selection)", ours(sel) == ["A", "B", "C"], "ours %s" % ours(sel), r)


# Select Duplicate Points (selectduplicatepoints), tolerance 0.01, over the whole project: A or D (which share
# a position) must be selected; which of the pair TBC picks isn't fixed by the test.
def t_select_duplicate_points():
    clear()
    open_cmd("selectduplicatepoints")
    r = fill([["MinimumDistance", "0.01"]], press="OK", wait=3)
    sel = selected()
    ok = "A" in ours(sel) or "D" in ours(sel)
    record("Select Duplicate Points", ok, "selected %d (whole project); ours %s (A and D share a position)" % (len(sel), ours(sel)), r)


# Select by Elevation (selectbyelevation), 15 to 25, "entirely within range": B (z 20) but none of A, C, D.
def t_select_by_elevation():
    clear()
    open_cmd("selectbyelevation")
    r = fill([["m_MinElevationValue", "15"], ["m_MaxElevationValue", "25"], ["m_EntirelyWithinRangeRadio", True]], press="OK", wait=3)
    sel = selected()
    o = ours(sel)
    ok = "B" in o and not set(o) & {"A", "C", "D"}
    record("Select by Elevation (15-25, entirely)", ok, "selected %d (whole project); ours %s" % (len(sel), o), r)


# Select Observations (selectobservations) by type "Total Station Observation": exercises the checked-list box
# (clbType). Always records PASS: it only reports how many total-station observations TBC selected.
def t_select_observations():
    clear()
    open_cmd("selectobservations")
    r = fill([["clbType", "Total Station Observation"]], press="OK", wait=3)
    sel = selected()
    record("Select Observations (type)", True, "selected %d total-station observations in the project" % len(sel), r)


# Select by Layer (selectbylayer): ticking the layer in its checked-list box selects straight away (no OK is
# pressed); exactly our 4 points and 2 lines must be selected. The panel is closed afterwards.
def t_select_by_layer():
    clear()
    open_cmd("selectbylayer")
    r = fill([["LayerCheckedListBox", LAYER]], wait=2)
    sel = selected()
    S.run_ipy("command_ui", "close", {})
    ok = ours(sel) == sorted(list(SER) + list(OBJ)) and len(sel) == len(SER) + len(OBJ)
    record("Select by Layer", ok, "selected %d: ours %s" % (len(sel), ours(sel)), r)


# Select by Polygon (selectbypolygon) with the box as boundary (picker m_BoundaryEntity takes its serial),
# "Inside boundary": A, B and D, not C (ignoring the box itself).
def t_select_by_polygon():
    clear()
    open_cmd("selectbypolygon")
    r = fill([["m_BoundaryEntity", OBJ["box"]], ["cb_SelectType", "Inside boundary"]], press="OK", wait=3)
    sel = selected()
    o = [x for x in ours(sel) if x != "box"]
    ok = o == ["A", "B", "D"]
    record("Select by Polygon (inside boundary)", ok, "selected %d; ours %s (expected A, B, D)" % (len(sel), ours(sel)), r)


# Select Similar (selectsimilar) to point A, matching on Feature code only (every other enabled attribute
# checkbox is unticked): A and C (code SELA) but not B.
def t_select_similar():
    clear()
    open_cmd("selectsimilar")
    r = fill([["selectEntity", SER["A"]], ["chkAllProperties", False]])
    st = S.run_ipy("command_ui", "state", {})
    # only the attributes that apply to the source object are enabled (for a point: Feature code, Feature locked, Layer)
    boxes = [f["id"] for f in st["fields"] if f["kind"] == "bool" and f.get("enabled", True)]
    vals = [[b, b == "chkFeatureCode"] for b in boxes if b != "chkAllProperties"]
    r = fill(vals, press="OK", wait=3)
    sel = selected()
    o = ours(sel)
    ok = "A" in o and "C" in o and "B" not in o
    record("Select Similar (feature code of A)", ok, "selected %d; ours %s" % (len(sel), o), r)


# Advanced select / Quick Select (quickselect): replace the selection with Points whose Feature Code equals
# SELB. The panel's fields appear step by step (object type -> property -> operator -> value), so it is
# re-read after each fill and the option texts are looked up rather than hard-coded; the prints are
# diagnostics. Passes when exactly one object, B, is selected.
def t_quick_select():
    clear()
    open_cmd("quickselect")
    st = S.run_ipy("command_ui", "state", {})
    types = [f.get("options") for f in st["fields"] if f["id"] == "m_cbObjectType"][0] or []
    print("      quick select data types (sample):", types[:12])
    r = fill([["m_rbEntireReplace", True], ["m_cbObjectType", "Point"], ["m_rbDataWithTheFollowing", True]])
    st = S.run_ipy("command_ui", "state", {})
    print("      quick select fields:", [(f["id"], f.get("value"), (f.get("options") or [])[:8]) for f in st["fields"]])
    props = [f.get("options") for f in st["fields"] if f["id"] == "m_cbProperties"][0] or []
    fc = [p for p in props if p.lower().replace(" ", "") == "featurecode"]
    r = fill([["m_cbProperties", fc[0] if fc else "Feature Code"]])
    st = S.run_ipy("command_ui", "state", {})
    print("      after property:", [(f["id"], f.get("value"), (f.get("options") or [])[:8]) for f in st["fields"] if f["id"] in ("m_cbPrimaryField", "m_cbOperator", "This_value")])
    ops = [f.get("options") for f in st["fields"] if f["id"] == "m_cbOperator"][0] or []
    eq = [o for o in ops if o.strip().lower() == "= equals"]
    # the value box depends on the property: a text box (This_value) or, for Feature Code, a dropdown (ValueCombo)
    vbox = [f["id"] for f in st["fields"] if f["id"] in ("ValueCombo", "This_value")]
    print("      value box:", vbox, [(f["id"], (f.get("options") or [])[:10]) for f in st["fields"] if f["id"] == "ValueCombo"])
    r = fill(([["m_cbOperator", eq[0]]] if eq else []) + [[vbox[0], "SELB"]], press="OK", wait=3)
    sel = selected()
    record("Advanced select (Point, feature code = SELB)", ours(sel) == ["B"] and len(sel) == 1, "selected %d; ours %s" % (len(sel), ours(sel)), r)


# Invert Selection (invertselection, run directly, no panel) starting from {A}: A is no longer selected and
# B, C and D are.
def t_invert_selection():
    S.call_bridge("set_selection", {"serials": [SER["A"]]})
    total = None
    S.t_run_command({"key": "invertselection"})
    S.wait_idle()
    sel = selected()
    o = ours(sel)
    ok = "A" not in o and {"B", "C", "D"} <= set(o)
    record("Invert Selection", ok, "selected %d after inverting {A}; ours %s" % (len(sel), o))
    # a whole-project selection is heavy (16k objects here); clear it straight away and let TBC settle
    clear()
    S.wait_idle()
    S.pace_command()


# Select All (command key "all", run directly): every one of our points and lines is in the selection.
def t_select_all():
    clear()
    S.t_run_command({"key": "all"})
    S.wait_idle()
    sel = selected()
    o = ours(sel)
    ok = set(o) == set(SER) | set(OBJ)
    record("Select All", ok, "selected %d objects; all of ours included: %s" % (len(sel), ok))
    clear()


TESTS = [t_select_points, t_select_points_by_id, t_add_to_selection, t_select_duplicate_points, t_select_by_elevation,
         t_select_observations, t_select_by_layer, t_select_by_polygon, t_select_similar, t_quick_select,
         t_invert_selection, t_select_all]

if __name__ == "__main__":
    # teardown (unless --keep): clear the selection, then delete the layer's contents, the layer and leftover windows
    run(TESTS, sys.argv[1:], setup, lambda: None if "--keep" in sys.argv else (clear(), cleanup([LAYER], base_forms=BASE_FORMS)))
    json.dump({"results": __import__("tbc_testkit").results}, open("selection_results.json", "w"), indent=1)
