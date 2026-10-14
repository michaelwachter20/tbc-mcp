# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Live tests of the Survey > COGO tools on throwaway points (layer MCP_SURVTEST). py -3.12 survey_cogo_tests.py [names]"""
import math, sys
from tbc_testkit import S, record, close, base, points, point, entities, make_points, make_line, open_cmd, fill, click, cleanup, run

LAYER = "MCP_SURVTEST"
E0, N0 = base(2000)
BASE_FORMS = set(f["id"] for f in S.run_ipy("command_ui", "forms", {}))


def setup():
    S.call_bridge("create_layer", {"name": LAYER})
    print("test area: E %.2f N %.2f" % (E0, N0))


def t_rename():
    pts = make_points(LAYER, [(E0, N0, 1), (E0 + 5, N0, 1)])
    names = [p["name"] for p in pts]
    open_cmd("renamepoints", [p["serial"] for p in pts])
    r = fill([["chkReport", False], ["Add constant", True], ["parameterBox", "1000"]], press="OK", wait=2)
    now = sorted(p["name"] for p in points(LAYER) if p["serial"] in [q["serial"] for q in pts])
    want = sorted(str(int(n) + 1000) for n in names)
    record("Rename Points", now == want, "%s -> %s (add constant 1000)" % (names, now), r)


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
    """Duplicate point IDs -> Merge Points (Identical) -> tick the 2nd point's Included cell via ui_grid -> OK."""
    nid = str(int(S.call_bridge("execute_python", {"code": "args = []\n" + S.NEXT_ID_CODE, "transaction": False})["result"]["max_numeric"]) + 1)
    r = S.t_create_points({"allow_duplicates": True, "points": [
        {"name": nid, "easting": E0 + 8, "northing": N0 + 45, "elevation": 3, "layer": LAYER},
        {"name": nid, "easting": E0 + 8.01, "northing": N0 + 45.01, "elevation": 3, "layer": LAYER}]})
    a, b = [p["serial"] for p in r["points"]]
    open_cmd("mergepoints", [a, b])
    fill([["Identical", True]])
    rows = S.t_ui_grid({"action": "read", "grid": "ugMergeDuplicateCandidates"})["rows"]
    excluded = [x for x in rows if x.get("Included") is False]
    g = None
    if excluded:
        g = S.t_ui_grid({"action": "set", "grid": "ugMergeDuplicateCandidates",
                         "row": {"_band": excluded[0]["_band"], "PointID": nid, "Included": False}, "column": "Included", "value": True})
    r2 = click("OK", wait=2)
    alive = S.call_bridge("execute_python", {"code": "args = %r\n" % [a, b] + S.EXISTS_CODE, "transaction": False})["result"]
    record("Merge Points", len(alive) == 1, "2 duplicates of %s -> %d left (Included ticked via ui_grid: %s)" % (nid, len(alive), g and g.get("now")), [g, r2])


def t_explode_points():
    """Explode a real multi-observation point found by Find Explodable Points, verify, then Undo."""
    open_cmd("explodepointcmd", [])
    click("Find Explodable Points", wait=3)
    rows = S.t_ui_grid({"action": "read", "grid": "pointList", "limit": 5})["rows"]
    if not rows:
        record("Explode Points", False, "no explodable points in the project")
        return
    pid = str(list(rows[0].values())[0])
    total0 = S.call_bridge("project_info")["point_count"]
    code = ("ui = TrimbleOffice.TheOffice.MainForm.CommandHost.TopCommand.CommandUI\n"
            "def find(c, n):\n    if c.Name == n: return c\n    for k in c.Controls:\n        r = find(k, n)\n        if r is not None: return r\n"
            "g = find(ui, 'pointList')\ng.ClearSelection()\nrow = [r for r in g.Rows if str(r.Cells[0].Value) == %r][0]\n"
            "g.CurrentCell = row.Cells[0]\nrow.Selected = True\nresult = int(str(row.Cells[1].Value))\n") % pid
    n = S.call_bridge("execute_python", {"code": code, "transaction": False})["result"]
    r = click("Explode", wait=3)
    total1 = S.call_bridge("project_info")["point_count"]
    S.run_ipy("command_ui", "close", {"all": True})
    S.t_run_command({"key": "undo"})
    S.wait_idle()
    total2 = S.call_bridge("project_info")["point_count"]
    record("Explode Points", total1 - total0 == n - 1 and total2 == total0,
           "point %s (%d observations): points %d -> %d after Explode, %d after Undo" % (pid, n, total0, total1, total2), r)


def t_merge_explode():
    pts = make_points(LAYER, [(E0, N0 + 40, 3), (E0 + 0.02, N0 + 40.01, 3.01)])
    n0 = len(points(LAYER))
    open_cmd("mergepoints", [p["serial"] for p in pts])
    # points 0.022 ft apart: the default 0.003 ft tolerance leaves the 2nd point 'Included: False' -> widen it
    r = fill([["Ignored", True], ["chkSelectPointsWithin", True], ["MinimumDistance", "0.1"]], press="OK", wait=2)
    n1 = len(points(LAYER))
    record("Merge Points", n1 == n0 - 1, "points on layer %d -> %d (2 merged into 1)" % (n0, n1), r)
    survivors = [p for p in points(LAYER) if p["serial"] in [q["serial"] for q in pts]]
    if not survivors:
        record("Explode Points", False, "no merged point to explode")
        return
    open_cmd("explodepointcmd", [survivors[0]["serial"]])
    r1 = click("Find Explodable Points", wait=2)
    st = S.t_command_ui_inspect({"include_text": False})
    grids = S.run_ipy("command_ui", "state", {}).get("grids")
    r2 = click("Explode", wait=2)
    n2 = len(points(LAYER))
    record("Explode Points", n2 == n0, "points on layer %d -> %d (merged point split back into 2)" % (n1, n2), [r1, r2])


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


def t_transform():
    pts = make_points(LAYER, [(E0, N0 + 80, 1), (E0 + 10, N0 + 80, 1)])
    open_cmd("transformsurveypoints", [p["serial"] for p in pts])
    r = fill([["eastingCheckBox", True], ["deltaEasting", "15"]], press="Apply", wait=2)
    now = [x for x in points(LAYER) if x["serial"] in [p["serial"] for p in pts]]
    ok = len(now) == 2 and all(close((x["easting"],), (e + 15,)) for x, e in zip(sorted(now, key=lambda x: x["easting"]), (E0, E0 + 10)))
    record("Transform Survey Points", ok, "eastings -> %s (expected +15)" % [round(x["easting"] - E0, 3) for x in now], r)


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


TESTS = [t_rename, t_average, t_merge, t_explode_points, t_move_survey_point, t_transform, t_integrate]

if __name__ == "__main__":
    run(TESTS, sys.argv[1:], setup, lambda: cleanup([LAYER], base_forms=BASE_FORMS))
