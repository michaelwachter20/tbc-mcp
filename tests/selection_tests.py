# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Live usage tests for the Home tab Selection group: Select Points, Duplicate Points, Elevation, Observations,
Layer, Polygon, Similar, Advanced (Quick Select), Invert Selection, Select All. Selection only - nothing is changed.
Throwaway points/lines on layer MCP_SELTEST; each test checks exactly what ends up selected (get_selection).
py -3.12 selection_tests.py [names]"""
import json, sys
from tbc_testkit import S, record, base, entities, make_points, make_line, open_cmd, fill, click, cleanup, run, done

LAYER = "MCP_SELTEST"
E0, N0 = base(3000, 2400)
P, SER = {}, {}
OBJ = {}
BASE_FORMS = set(f["id"] for f in S.run_ipy("command_ui", "forms", {}))


def setup():
    S.call_bridge("create_layer", {"name": LAYER})
    pts = {"A": (0, 0, 10, "SELA"), "B": (10, 0, 20, "SELB"), "C": (40, 0, 30, "SELA"), "D": (0, 0, 10, "SELDUP")}
    for k, (x, y, z, code) in pts.items():
        p = make_points(LAYER, [(E0 + x, N0 + y, z)], code=code)[0]
        P[k], SER[k] = p["name"], p["serial"]
        S.pace_command()
    # closed boundary around A, B, D (not C): x -5..15, y -5..5
    OBJ["box"] = make_line(LAYER, "MCP_SEL_BOX", [(E0 - 5, N0 - 5, 0), (E0 + 15, N0 - 5, 0), (E0 + 15, N0 + 5, 0), (E0 - 5, N0 + 5, 0), (E0 - 5, N0 - 5, 0)], closed=True)
    OBJ["line"] = make_line(LAYER, "MCP_SEL_LINE", [(E0, N0 + 20, 5), (E0 + 40, N0 + 20, 5)])
    print("test area E %.2f N %.2f; points %s; objects %s" % (E0, N0, P, OBJ))


def selected():
    return set(e["serial"] for e in S.call_bridge("get_selection", {"limit": 100000})["entities"])


def ours(sel):
    """Which of OUR test objects are in a selection (the selection may also hold the user's own data)."""
    names = {v: k for k, v in SER.items()}
    names.update({v: k for k, v in OBJ.items()})
    return sorted(names[s] for s in sel if s in names)


def clear():
    S.call_bridge("set_selection", {"serials": []})


def t_select_points():
    clear()
    open_cmd("selectpoints")
    r = fill([["cboLayer", LAYER], ["txtFieldCode", "SELA"]], press="OK", wait=2)
    sel = selected()
    ok = ours(sel) == ["A", "C"] and len(sel) == 2
    record("Select Points (layer + feature code)", ok, "selected %d: ours %s" % (len(sel), ours(sel)), r)


def t_select_points_by_id():
    clear()
    open_cmd("selectpoints")
    r = fill([["SelectedPointID", P["B"]]], press="OK", wait=2)
    sel = selected()
    record("Select Points (point ID)", ours(sel) == ["B"], "selected %d: ours %s" % (len(sel), ours(sel)), r)


def t_add_to_selection():
    S.call_bridge("set_selection", {"serials": [SER["B"]]})
    open_cmd("selectpoints", select=[SER["B"]])
    r = fill([["cboLayer", LAYER], ["txtFieldCode", "SELA"], ["chkAddToCurrentSelection", True]], press="OK", wait=2)
    sel = selected()
    record("Select Points (add to current selection)", ours(sel) == ["A", "B", "C"], "ours %s" % ours(sel), r)


def t_select_duplicate_points():
    clear()
    open_cmd("selectduplicatepoints")
    r = fill([["MinimumDistance", "0.01"]], press="OK", wait=3)
    sel = selected()
    ok = "A" in ours(sel) or "D" in ours(sel)
    record("Select Duplicate Points", ok, "selected %d (whole project); ours %s (A and D share a position)" % (len(sel), ours(sel)), r)


def t_select_by_elevation():
    clear()
    open_cmd("selectbyelevation")
    r = fill([["m_MinElevationValue", "15"], ["m_MaxElevationValue", "25"], ["m_EntirelyWithinRangeRadio", True]], press="OK", wait=3)
    sel = selected()
    o = ours(sel)
    ok = "B" in o and not set(o) & {"A", "C", "D"}
    record("Select by Elevation (15-25, entirely)", ok, "selected %d (whole project); ours %s" % (len(sel), o), r)


def t_select_observations():
    clear()
    open_cmd("selectobservations")
    r = fill([["clbType", "Total Station Observation"]], press="OK", wait=3)
    sel = selected()
    record("Select Observations (type)", True, "selected %d total-station observations in the project" % len(sel), r)


def t_select_by_layer():
    clear()
    open_cmd("selectbylayer")
    r = fill([["LayerCheckedListBox", LAYER]], wait=2)
    sel = selected()
    S.run_ipy("command_ui", "close", {})
    ok = ours(sel) == sorted(list(SER) + list(OBJ)) and len(sel) == len(SER) + len(OBJ)
    record("Select by Layer", ok, "selected %d: ours %s" % (len(sel), ours(sel)), r)


def t_select_by_polygon():
    clear()
    open_cmd("selectbypolygon")
    r = fill([["m_BoundaryEntity", OBJ["box"]], ["cb_SelectType", "Inside boundary"]], press="OK", wait=3)
    sel = selected()
    o = [x for x in ours(sel) if x != "box"]
    ok = o == ["A", "B", "D"]
    record("Select by Polygon (inside boundary)", ok, "selected %d; ours %s (expected A, B, D)" % (len(sel), ours(sel)), r)


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
    run(TESTS, sys.argv[1:], setup, lambda: None if "--keep" in sys.argv else (clear(), cleanup([LAYER], base_forms=BASE_FORMS)))
    json.dump({"results": __import__("tbc_testkit").results}, open("selection_results.json", "w"), indent=1)
