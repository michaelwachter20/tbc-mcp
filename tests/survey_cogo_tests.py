# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Live tests of the Survey > COGO tools on throwaway points (layer MCP_SURVTEST). py -3.12 survey_cogo_tests.py [names]

Needs TBC
    Yes: TBC 2026.10 with a project open (use a copy) and the MCP Bridge macro on. The module talks to TBC
    at import time (Plan View centre, list of open windows). Uses the shared helpers in tests\\tbc_testkit.py.

How to run (from the repository root)
    py -3.12 tests\\survey_cogo_tests.py                    all tests in TESTS
    py -3.12 tests\\survey_cogo_tests.py rename average     only these (function names without "t_")

What it creates and cleans up
    Layer MCP_SURVTEST with small groups of points (next free numeric IDs) 2000 display units east of the
    Plan View centre, plus a closed square linestring for Integrate to Geometry. The teardown
    (tbc_testkit.cleanup) deletes everything on the layer, the layer, and any window opened during the run.
    Integrate to Geometry puts its points on the default "Points" layer; that test deletes them itself.
    Explode Points works on a real multi-observation point of the project and puts it back with Undo.

What it writes
    Console output only (no results file). TBC error popups go to knowledge\\memory\\tbc_errors.log via the
    server, and stop the run.

Pass / fail
    One PASS/FAIL line per check, read back from the model (point IDs, coordinates within 0.01, point
    counts); "N/M passed" at the end. FAILs don't change the exit code.
"""
import math, sys
from tbc_testkit import S, record, close, base, points, point, entities, make_points, make_line, open_cmd, fill, click, cleanup, run

LAYER = "MCP_SURVTEST"
E0, N0 = base(2000)
# windows already open before the run; cleanup() closes any other non-modal window the tests left behind
BASE_FORMS = set(f["id"] for f in S.run_ipy("command_ui", "forms", {}))


def setup():
    """Create the throwaway layer and print the test area's origin."""
    S.call_bridge("create_layer", {"name": LAYER})
    print("test area: E %.2f N %.2f" % (E0, N0))


# Rename Points (renamepoints), "Add constant" 1000 with the report checkbox (chkReport) off:
# both selected points' numeric IDs must go up by exactly 1000.
def t_rename():
    pts = make_points(LAYER, [(E0, N0, 1), (E0 + 5, N0, 1)])
    names = [p["name"] for p in pts]
    open_cmd("renamepoints", [p["serial"] for p in pts])
    r = fill([["chkReport", False], ["Add constant", True], ["parameterBox", "1000"]], press="OK", wait=2)
    now = sorted(p["name"] for p in points(LAYER) if p["serial"] in [q["serial"] for q in pts])
    want = sorted(str(int(n) + 1000) for n in names)
    record("Rename Points", now == want, "%s -> %s (add constant 1000)" % (names, now), r)


# Average Points (createaveragepointcmd): three selected points -> Add -> Compute a new point with the next
# numeric ID. It must sit at the plain mean of the three: (E0+1, N0+20.667, z 4).
def t_average():
    pts = make_points(LAYER, [(E0, N0 + 20, 2), (E0 + 2, N0 + 20, 4), (E0 + 1, N0 + 22, 6)])
    open_cmd("createaveragepointcmd", [p["serial"] for p in pts])
    new_id = str(int(max(int(p["name"]) for p in pts)) + 1)
    r1 = fill([["Point ID", new_id], ["Layer", LAYER]])
    r2 = click("Add")
    r3 = click("Compute", wait=2)
    a = point(new_id)
    ok = a is not None and close((a["easting"], a["northing"], a["elevation"]), (E0 + 1, N0 + 20 + 2 / 3.0, 4))
    record("Average Points", ok, "new point %s at %s (expected E0+1, N0+20.667, z 4)" % (
        new_id, (round(a["easting"] - E0, 3), round(a["northing"] - N0, 3), a["elevation"]) if a else None), [r1, r2, r3])


def t_merge():
    """Duplicate point IDs -> Merge Points (Identical) -> tick the 2nd point's Included cell via ui_grid -> OK.

    Exercises Merge Points (mergepoints) and the ui_grid tool on its Infragistics candidates grid
    (ugMergeDuplicateCandidates). Two points with the same ID, 0.01 apart, are made with allow_duplicates.
    Passes when only one of the two serials still exists afterwards.
    """
    # next free numeric ID, computed with the server's own NEXT_ID_CODE snippet run inside TBC
    nid = str(int(S.call_bridge("execute_python", {"code": "args = []\n" + S.NEXT_ID_CODE, "transaction": False})["result"]["max_numeric"]) + 1)
    r = S.t_create_points({"allow_duplicates": True, "points": [
        {"name": nid, "easting": E0 + 8, "northing": N0 + 45, "elevation": 3, "layer": LAYER},
        {"name": nid, "easting": E0 + 8.01, "northing": N0 + 45.01, "elevation": 3, "layer": LAYER}]})
    a, b = [p["serial"] for p in r["points"]]
    open_cmd("mergepoints", [a, b])
    fill([["Identical", True]])
    rows = S.t_ui_grid({"action": "read", "grid": "ugMergeDuplicateCandidates"})["rows"]
    # a candidate row TBC left un-ticked is ticked through ui_grid (row matched by its band and point ID)
    excluded = [x for x in rows if x.get("Included") is False]
    g = None
    if excluded:
        g = S.t_ui_grid({"action": "set", "grid": "ugMergeDuplicateCandidates",
                         "row": {"_band": excluded[0]["_band"], "PointID": nid, "Included": False}, "column": "Included", "value": True})
    r2 = click("OK", wait=2)
    # S.EXISTS_CODE returns which of the given serials still exist in the project
    alive = S.call_bridge("execute_python", {"code": "args = %r\n" % [a, b] + S.EXISTS_CODE, "transaction": False})["result"]
    record("Merge Points", len(alive) == 1, "2 duplicates of %s -> %d left (Included ticked via ui_grid: %s)" % (nid, len(alive), g and g.get("now")), [g, r2])


def t_explode_points():
    """Explode a real multi-observation point found by Find Explodable Points, verify, then Undo.

    Exercises Explode Points (explodepointcmd). This one touches project data (not a throwaway object), so
    it relies on TBC's Undo to put it back. Passes when the point count rose by (observations - 1) after
    Explode and is back to the original after Undo. Records a FAIL when the project has no explodable point.
    """
    open_cmd("explodepointcmd", [])
    click("Find Explodable Points", wait=3)
    rows = S.t_ui_grid({"action": "read", "grid": "pointList", "limit": 5})["rows"]
    if not rows:
        record("Explode Points", False, "no explodable points in the project")
        return
    # first column of the first row is the point ID
    pid = str(list(rows[0].values())[0])
    total0 = S.call_bridge("project_info")["point_count"]
    # IronPython run inside TBC: walk the open command panel's WinForms controls to find the 'pointList'
    # grid, select the row for that point, and return its second cell (the number of observations)
    code = ("ui = TrimbleOffice.TheOffice.MainForm.CommandHost.TopCommand.CommandUI\n"
            "def find(c, n):\n    if c.Name == n: return c\n    for k in c.Controls:\n        r = find(k, n)\n        if r is not None: return r\n"
            "g = find(ui, 'pointList')\ng.ClearSelection()\nrow = [r for r in g.Rows if str(r.Cells[0].Value) == %r][0]\n"
            "g.CurrentCell = row.Cells[0]\nrow.Selected = True\nresult = int(str(row.Cells[1].Value))\n") % pid
    n = S.call_bridge("execute_python", {"code": code, "transaction": False})["result"]
    r = click("Explode", wait=3)
    total1 = S.call_bridge("project_info")["point_count"]
    S.run_ipy("command_ui", "close", {"all": True})
    # put the project's point back as it was, then let TBC recompute before counting again
    S.t_run_command({"key": "undo"})
    S.wait_idle()
    total2 = S.call_bridge("project_info")["point_count"]
    record("Explode Points", total1 - total0 == n - 1 and total2 == total0,
           "point %s (%d observations): points %d -> %d after Explode, %d after Undo" % (pid, n, total0, total1, total2), r)


# Move Survey Point (movesurveypoint): the point (given to the "Point ID" picker by serial) is moved onto a
# second point (given by ID in "To"); its position must match (E0+10, N0+65). The detail line also shows the
# new name (TBC is expected to add "(MOVED)").
def t_move_survey_point():
    p = make_points(LAYER, [(E0, N0 + 60, 5)])[0]
    target = make_points(LAYER, [(E0 + 10, N0 + 65, 5)])[0]
    open_cmd("movesurveypoint")
    r = fill([["Point ID", p["serial"]], ["To", target["name"]]], press="OK", wait=2)
    q = [x for x in points(LAYER) if x["serial"] == p["serial"]]
    q = q[0] if q else None
    ok = q is not None and close((q["easting"], q["northing"]), (E0 + 10, N0 + 65))
    record("Move Survey Point", ok, "point now %s named %s (expected E0+10, N0+65, name with (MOVED))" % (
        (round(q["easting"] - E0, 3), round(q["northing"] - N0, 3)) if q else None, q["name"] if q else None), r)


# Transform Survey Points (transformsurveypoints): delta easting 15 only; both points' eastings must rise by 15.
def t_transform():
    pts = make_points(LAYER, [(E0, N0 + 80, 1), (E0 + 10, N0 + 80, 1)])
    open_cmd("transformsurveypoints", [p["serial"] for p in pts])
    r = fill([["eastingCheckBox", True], ["deltaEasting", "15"]], press="Apply", wait=2)
    now = [x for x in points(LAYER) if x["serial"] in [p["serial"] for p in pts]]
    ok = len(now) == 2 and all(close((x["easting"],), (e + 15,)) for x, e in zip(sorted(now, key=lambda x: x["easting"]), (E0, E0 + 10)))
    record("Transform Survey Points", ok, "eastings -> %s (expected +15)" % [round(x["easting"] - E0, 3) for x in now], r)


# Integrate to Geometry (geometrypointintegratecmd) on a closed 30 x 30 square: Process must add exactly
# 4 points, one at each corner (within 0.02). The new points are deleted at the end of the test because
# they land on the 'Points' layer, which the suite's cleanup doesn't touch.
def t_integrate():
    s = make_line(LAYER, "INTEG", [(E0, N0 + 100, 2), (E0 + 30, N0 + 100, 2), (E0 + 30, N0 + 130, 2), (E0, N0 + 130, 2)], closed=True)
    # new points go to the DEFAULT 'Points' layer (no layer option) and skip IDs that already exist
    total0 = S.call_bridge("project_info")["point_count"]
    open_cmd("geometrypointintegratecmd", [s])
    start = str(int(S.call_bridge("execute_python", {"code": "args = []\n" + S.NEXT_ID_CODE, "transaction": False})["result"]["max_numeric"]) + 1)
    r = fill([["Starting point ID", start]], press="Process", wait=3)
    st = S.t_command_ui_inspect({"include_text": True})
    total1 = S.call_bridge("project_info")["point_count"]
    new = [p for p in S.call_bridge("list_points", {"layer": "Points", "limit": 20000})["points"]
           if p["name"].isdigit() and int(p["name"]) >= int(start)]
    corners = [(E0, N0 + 100), (E0 + 30, N0 + 100), (E0 + 30, N0 + 130), (E0, N0 + 130)]
    on_corners = all(any(close((p["easting"], p["northing"]), c, 0.02) for p in new) for c in corners)
    record("Integrate to Geometry", total1 - total0 == 4 and on_corners, "4 points at the polygon corners on layer 'Points' (ids %s); report: %s" % (
        sorted(p["name"] for p in new), [t for t in st.get("texts", []) if "points were added" in t][:1]), r)
    if new:
        S.t_delete_entities({"serials": [p["serial"] for p in new]})


# run order
TESTS = [t_rename, t_average, t_merge, t_explode_points, t_move_survey_point, t_transform, t_integrate]

if __name__ == "__main__":
    # teardown: delete the layer's contents and the layer, and close windows that weren't open at the start
    run(TESTS, sys.argv[1:], setup, lambda: cleanup([LAYER], base_forms=BASE_FORMS))
