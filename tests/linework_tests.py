# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Live usage tests for the Linework tab on throwaway objects (layer MCP_LWTEST). py -3.12 linework_tests.py [names]
Reference locations are numeric points (user preference) typed as point IDs into TBC's coordinate boxes."""
import json, math, sys
from tbc_testkit import S, record, close, base, points, entities, make_points, make_line, open_cmd, fill, click, cleanup, run, done

LAYER = "MCP_LWTEST"
E0, N0 = base(3000)
P = {}  # alias -> point ID
BASE_FORMS = set(f["id"] for f in S.run_ipy("command_ui", "forms", {}))

GEOM = r"""
import math
o = bridge.lookup(prj, args)
f = bridge.factor(prj)
out = {'type': o.GetType().FullName, 'name': str(getattr(o, 'Name', '') or '')}
pts = []
try:
    ps = o.ComputePolySeg()
    pts = [(p.X * f, p.Y * f, (p.Z * f if p.Z == p.Z else None)) for p in ps.ToPoint3DArray()]
except Exception as ex:
    out['polyseg_error'] = str(ex)[:80]
out['points'] = pts[:200]
for a in ('Radius', 'Closed', 'Elevation', 'Area', 'Length'):
    try:
        v = getattr(o, a)
        out[a.lower()] = float(v) * (f if a in ('Radius', 'Elevation', 'Length') else (f * f if a == 'Area' else 1)) if not isinstance(v, bool) else bool(v)
    except Exception:
        pass
result = out
"""


def geom(serial):
    return S.call_bridge("execute_python", {"code": "args = %d\n" % serial + GEOM, "transaction": False})["result"]


def new_objects(before):
    return [e for e in entities(LAYER) if e["serial"] not in before and not e["type"].endswith("Point")]


def rel(pts):
    return [(round(x - E0, 3), round(y - N0, 3), None if z is None else round(z, 3)) for x, y, z in pts]


def setup():
    S.call_bridge("create_layer", {"name": LAYER})
    coords = {"A": (0, 0, 10), "B": (100, 0, 10), "C": (100, 50, 10), "D": (0, 50, 10), "M": (50, 50, 10),
              "R1": (0, 200, 10), "R2": (40, 230, 10), "Q": (50, 100, 10),
              # two points on each edge of the A-B-C-D rectangle, for Capture Outline
              "O1": (20, 0, 10), "O2": (80, 0, 10), "O3": (100, 10, 10), "O4": (100, 40, 10),
              "O5": (80, 50, 10), "O6": (20, 50, 10), "O7": (0, 40, 10), "O8": (0, 10, 10),
              "IN": (50, 25, 10)}
    made = make_points(LAYER, [(E0 + x, N0 + y, z) for x, y, z in coords.values()])
    for k, p in zip(coords, made):
        P[k] = p["name"]
    print("test area E %.2f N %.2f; reference points %s" % (E0, N0, P))


def ents_before():
    return set(e["serial"] for e in entities(LAYER))


# ---------------------------------------------------------------- creation tools
def t_polyline():
    b = ents_before()
    open_cmd("createpolyline")
    r = fill([["Name", "LW_PL"], ["Layer", LAYER], ["Elevation", "5"], ["Specify individual points", True]])
    for k in ("A", "B", "C"):
        r = fill([["Next point", P[k]]], press="Add Point", wait=1)
    click("Close", wait=1)
    new = new_objects(b)
    g = geom(new[0]["serial"]) if new else {}
    v = rel(g.get("points", []))
    ok = len(new) == 1 and len(v) >= 3 and close(v[0][:2], (0, 0)) and close(v[-1][:2], (100, 50))
    record("Create Polyline", ok, "%s -> %s vertices %s" % ([x["type"] for x in new], len(v), v[:4]), r)


def t_circle():
    b = ents_before()
    open_cmd("createcircle")
    r = fill([["Name", "LW_CIRC"], ["Layer", LAYER], ["Elevation", "5"], ["Center point", P["Q"]], ["Radius", "20"]], press="Create", wait=1.5)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    g = geom(new[0]["serial"]) if new else {}
    pts = g.get("points", [])
    radii = [math.hypot(x - (E0 + 50), y - (N0 + 100)) for x, y, z in pts]
    ok = len(new) == 1 and radii and all(abs(rr - 20) < 0.05 for rr in radii)
    record("Create Circle", ok, "%s radius from vertices %s (expected 20 about Q)" % ([x["type"] for x in new], [round(rr, 3) for rr in radii[:4]]), r)


def t_three_point_circle():
    b = ents_before()
    open_cmd("createthreepointcircle")
    r = fill([["Name", "LW_C3"], ["Layer", LAYER], ["Elevation", "5"], ["Point one", P["A"]], ["Point two", P["B"]], ["Point three", P["M"]]], press="Apply", wait=1.5)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    g = geom(new[0]["serial"]) if new else {}
    pts = g.get("points", [])
    # circle through A(0,0) B(100,0) M(50,50): centre (50,0), radius 50
    radii = [math.hypot(x - (E0 + 50), y - N0) for x, y, z in pts]
    ok = len(new) == 1 and radii and all(abs(rr - 50) < 0.05 for rr in radii)
    record("Three-Point Circle", ok, "%s radius %s (expected 50, centre E0+50,N0)" % ([x["type"] for x in new], [round(rr, 3) for rr in radii[:3]]), r)


def t_arc():
    b = ents_before()
    st = open_cmd("createarc")
    opts = [f.get("options") for f in st["fields"] if f["label"] == "Create arc using"]
    r = fill([["Name", "LW_ARC"], ["Layer", LAYER], ["Elevation", "5"], ["Start point", P["A"]], ["Middle point", P["M"]], ["End point", P["B"]]], press="Apply", wait=1.5)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    g = geom(new[0]["serial"]) if new else {}
    v = rel(g.get("points", []))
    # TBC may store the arc either way round (seen B->A); check end points as a set and that it lies on r=50 about (50,0)
    ends = sorted([tuple(round(c) for c in v[0][:2]), tuple(round(c) for c in v[-1][:2])]) if v else []
    on = all(abs(math.hypot(x - 50, y) - 50) < 0.05 for x, y, z in v)
    ok = len(new) == 1 and ends == [(0, 0), (100, 0)] and on
    record("Create Arc", ok, "%s ends %s on r50 circle %s (3-point A-M-B); methods: %s" % ([x["type"] for x in new], ends, on, opts), r)


def t_rectangle():
    b = ents_before()
    open_cmd("createrectangle")
    r = fill([["Name", "LW_RECT"], ["Layer", LAYER], ["Elevation", "5"], ["Corner one", P["A"]], ["Corner two", P["C"]]], press="OK", wait=1.5)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    g = geom(new[0]["serial"]) if new else {}
    v = rel(g.get("points", []))
    xs = sorted(set(round(p[0]) for p in v)); ys = sorted(set(round(p[1]) for p in v))
    ok = len(new) == 1 and xs == [0, 100] and ys == [0, 50]
    record("Create Rectangle", ok, "%s corners x %s y %s (expected A..C = 100 x 50)" % ([x["type"] for x in new], xs, ys), r)


def t_three_point_rectangle():
    b = ents_before()
    open_cmd("createthreepointrectangle")
    r = fill([["Name", "LW_R3"], ["Layer", LAYER], ["Elevation", "5"], ["Corner one", P["R1"]], ["Corner two", P["R2"]], ["Width", "10"]], press="Apply", wait=1.5)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    g = geom(new[0]["serial"]) if new else {}
    v = rel(g.get("points", []))
    side = math.hypot(40, 30)
    ok = len(new) == 1 and len(v) >= 4
    record("Three-Point Rectangle", ok, "%s vertices %s (side R1-R2 = %.1f, width 10)" % ([x["type"] for x in new], v[:5], side), r)


def edit_linestring_vertices(keys):
    """In the Edit Linestring pane (after OK in Create Linestring/Polygon/Breakline): Type = Point ID, then one
    Save per vertex. Returns the edited line's serial."""
    st = S.run_ipy("command_ui", "state", {})
    line = [f for f in st["fields"] if f["label"] == "Line"][0]["value"]["serial"]
    fill([["LocationTypeComboBox", "Point ID"]])
    for k in keys:
        fill([["Point ID", P[k]]])
        click("Save", wait=1.2)  # separate click: Save must come after the box commits
    click("Close", wait=1.5)
    return line


def t_linestring():
    open_cmd("createlinestring")
    r = fill([["Name", "LW_LS"], ["Layer", LAYER]], press="OK", wait=2)
    line = edit_linestring_vertices(["A", "B", "C"])
    g = geom(line)
    v = rel(g.get("points", []))
    ok = [p[:2] for p in v] == [(0, 0), (100, 0), (100, 50)] and all(p[2] == 10 for p in v)
    record("Create Linestring", ok, "%s vertices %s (z from the points)" % (g.get("type"), v), r)


def t_polygon():
    open_cmd("createpolygon")
    r = fill([["Name", "LW_PG"], ["Layer", LAYER]], press="OK", wait=2)
    line = edit_linestring_vertices(["A", "B", "C", "D"])
    g = geom(line)
    v = rel(g.get("points", []))
    xs = sorted(set(round(p[0]) for p in v)); ys = sorted(set(round(p[1]) for p in v))
    ok = xs == [0, 100] and ys == [0, 50] and len(v) >= 4
    record("Create Polygon", ok, "%s vertices %s area %s closed %s" % (g.get("type"), v, g.get("area"), g.get("closed")), r)


SURF = "MCP_LW_SURF"


def t_breakline():
    # small throwaway surface from A,B,C,D,M (the project's own surface is 1M triangles: too slow to recompute)
    ser = [S.call_bridge("list_points", {"name_contains": P[k], "limit": 5})["points"][0]["serial"] for k in ("A", "B", "C", "D", "M")]
    open_cmd("surfacecreate", select=ser)
    fill([["Name", SURF]], press="OK", wait=2)
    S.wait_idle()
    done()
    S.pace_command()
    open_cmd("createbreakline")
    r = fill([["Name", "LW_BL"], ["Layer", LAYER], ["Add to surface", SURF]], press="OK", wait=2)
    line = edit_linestring_vertices(["A", "C"])
    S.wait_idle()
    g = geom(line)
    surf = [s for s in S.call_bridge("list_surfaces")["surfaces"] if s["name"] == SURF]
    v = rel(g.get("points", []))
    ok = [p[:2] for p in v] == [(0, 0), (100, 50)] and bool(surf)
    record("Create Breakline", ok, "%s vertices %s; surface %s" % (g.get("type"), v, surf), r)


def t_boundary():
    # Polygon mode keeps only Point + the last Additional point when points are typed (vertices need view picks),
    # so build the boundary from an existing closed line: Create Rectangle A..C, then "Polygon (from a line)".
    b0 = ents_before()
    open_cmd("createrectangle")
    fill([["Name", "LW_BND_SRC"], ["Layer", LAYER], ["Elevation", "5"], ["Corner one", P["A"]], ["Corner two", P["C"]]], press="OK", wait=1.5)
    S.run_ipy("command_ui", "close", {})
    src = new_objects(b0)[0]["serial"]
    S.pace_command()
    b = ents_before()
    open_cmd("createboundary")
    r = fill([["Name", "LW_BND"], ["Layer", LAYER], ["Polygon (from a line)", True], ["m_ctrlExistingEntity", src]], press="OK", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    g = geom(new[0]["serial"]) if new else {}
    v = rel(g.get("points", []))
    xs = sorted(set(round(p[0]) for p in v)); ys = sorted(set(round(p[1]) for p in v))
    ok = len(new) == 1 and xs == [0, 100] and ys == [0, 50]
    record("Create Boundary", ok, "%s vertices %s" % ([x["type"] for x in new], v), r)


def t_quick_line():
    b = ents_before()
    open_cmd("quickline")
    r = fill([["Name", "LW_QL"], ["Layer", LAYER]])
    steps = []
    for k in ("A", "B", "C"):
        r = fill([["Coordinate", P[k] + "\n"]])  # Enter adds the vertex (WPF box)
        steps.append([x.get("now") for x in r.get("set", [])] + [x.get("error") for x in r.get("errors", [])])
    print("      quick line steps:", steps)
    r = click("Apply", wait=1.5)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    g = geom(new[0]["serial"]) if new else {}
    v = rel(g.get("points", []))
    ok = len(new) == 1 and [p[:2] for p in v] == [(0, 0), (100, 0), (100, 50)]
    record("Quick Line", ok, "%s vertices %s" % ([x["type"] for x in new], v), r)


def t_best_fit_line():
    b = ents_before()
    ser = [S.call_bridge("list_points", {"name_contains": P[k], "limit": 5})["points"][0]["serial"] for k in ("A", "B")]
    open_cmd("bestfitline", select=ser)
    r = fill([["Line type", "Straight Line 2D (Plan View)"], ["Layer", LAYER]], press="OK", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    g = geom(new[0]["serial"]) if new else {}
    v = rel(g.get("points", []))
    ok = len(new) == 1 and v and all(abs(p[1]) < 0.01 for p in v)
    record("Best-Fit Line", ok, "%s through A,B: vertices %s" % ([x["type"] for x in new], v), r)


def t_outline():
    b = ents_before()
    open_cmd("captureoutline")
    r = fill([["Name (optional)", "LW_OUT"], ["Layer", LAYER]])
    for k in ("O1", "O2", "O3", "O4", "O5", "O6", "O7", "O8"):
        r = fill([["Coordinate", P[k]]])  # tab-out commit; Enter here means OK/finish (modal error with < 2 points)
    r = click("Close outline", wait=1.5)
    r = click("Ok", wait=1.5)
    new = new_objects(b)
    g = geom(new[0]["serial"]) if new else {}
    v = rel(g.get("points", []))
    corners = sorted(set((round(p[0]), round(p[1])) for p in v))
    ok = len(new) == 1 and corners == [(0, 0), (0, 50), (100, 0), (100, 50)]
    record("Capture Outline", ok, "%s corners %s (2 points per edge -> intersections)" % ([x["type"] for x in new], corners), r)


def rect_polyline(name):
    b = ents_before()
    open_cmd("createrectangle")
    fill([["Name", name], ["Layer", LAYER], ["Elevation", "5"], ["Corner one", P["A"]], ["Corner two", P["C"]]], press="OK", wait=1.5)
    S.run_ipy("command_ui", "close", {})
    S.pace_command()
    return new_objects(b)[0]["serial"]


def ln(name, pts):
    """Throwaway linestring through display coordinates relative to E0,N0 (z 10)."""
    return make_line(LAYER, name, [(E0 + x, N0 + y, 10) for x, y in pts])


def t_convert_to_linestring():
    src = rect_polyline("LW_CONV_SRC")
    b = ents_before()
    st = open_cmd("anz_converttolinestring", select=[src])
    r = fill([], press="OK", wait=2)
    S.run_ipy("command_ui", "close", {})
    after = entities(LAYER)
    new = [e for e in after if e["serial"] not in b]
    src_left = any(e["serial"] == src for e in after)
    g = geom(new[0]["serial"]) if new else {}
    corners = sorted(set((round(p[0]), round(p[1])) for p in rel(g.get("points", []))))
    ok = len(new) == 1 and "Linestring" in new[0]["type"] and corners == [(0, 0), (0, 50), (100, 0), (100, 50)]
    record("Convert To Linestring", ok, "%s corners %s; source polyline kept: %s" % ([x["type"] for x in new], corners, src_left), r)


def t_offset():
    line = ln("LW_OFF_SRC", [(0, 0), (100, 0)])
    b = ents_before()
    open_cmd("offsetlinestring")
    r = fill([["Line to offset", line], ["Offset distance", "10"], ["Side to offset", "Left"], ["Name", "LW_OFF"], ["Layer", LAYER]], press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = new_objects(b)
    v = rel(geom(new[0]["serial"])["points"]) if new else []
    ok = len(new) == 1 and v and all(abs(p[1] - 10) < 0.01 for p in v)
    record("Offset", ok, "%s vertices %s (10 left of an eastward line = north)" % ([x["type"] for x in new], v), r)


def t_fillet():
    line = ln("LW_FIL", [(0, 0), (100, 0), (100, 50)])
    open_cmd("filletchamfer")
    r = fill([["Fillet", True], ["Fillet radius", "10"], ["Apply to entire line", True], ["selLine1", line]], press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    g = geom(line)
    v = rel(g["points"])
    corner_gone = not any(close(p[:2], (100, 0), 0.01) for p in v)
    tangent = any(close(p[:2], (90, 0), 0.02) for p in v) and any(close(p[:2], (100, 10), 0.02) for p in v)
    ok = corner_gone and tangent
    record("Fillet", ok, "vertices %s (r10 fillet at B: tangent points (90,0) and (100,10))" % v[:8], r)


def t_trim_extend():
    bound = ln("LW_TE_BOUND", [(100, -20), (100, 70)])
    line = ln("LW_TE", [(0, 20), (50, 20)])
    # "One line to bounding lines" needs a pick in the view (which end); the selection-based mode needs no pick:
    # select the bounding line(s) + the line(s) to change, "Multiple lines to bounding lines"
    open_cmd("trimextendlines")
    r = fill([["Multiple lines to bounding lines", True]])
    r = fill([["memBoundariesMulti", [bound]], ["MultipleMemberSelection", [line]], ["MultipleBoundingExtendRadioButton", True]],
             press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    v = rel(geom(line)["points"])
    ok = v and close(v[-1][:2], (100, 20), 0.01)
    record("Trim/Extend", ok, "line now %s (extended to the bounding line x=100)" % v, r)


def t_divide_lines():
    line = ln("LW_DIV", [(0, 0), (100, 0)])
    b = ents_before()
    open_cmd("divideline", select=[line])
    r = fill([["Divide by number of separated objects", True], ["numUpDownDivideNum", 4]], press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    after = entities(LAYER)
    parts = [e for e in after if not e["type"].endswith("Point") and (e["serial"] not in b or e["serial"] == line)]
    lens = sorted(round(abs(rel(geom(e["serial"])["points"])[-1][0] - rel(geom(e["serial"])["points"])[0][0]), 2) for e in parts)
    ok = lens == [25.0, 25.0, 25.0, 25.0]
    record("Divide Lines", ok, "%d parts, lengths %s (100 ft into 4)" % (len(parts), lens), r)


def t_break():
    line = ln("LW_BRK", [(0, 0), (100, 0)])
    b = ents_before()
    open_cmd("breakline")
    r = fill([["Line", line], ["Distance along", "40"]], press="Break", wait=2)
    S.run_ipy("command_ui", "close", {})
    after = entities(LAYER)
    parts = [e for e in after if not e["type"].endswith("Point") and (e["serial"] not in b or e["serial"] == line)]
    spans = sorted([tuple(sorted((rel(geom(e["serial"])["points"])[0][0], rel(geom(e["serial"])["points"])[-1][0]))) for e in parts])
    ok = spans == [(0.0, 40.0), (40.0, 100.0)]
    record("Break", ok, "pieces %s (break at 40)" % spans, r)


def lines_now(b):
    return [e for e in entities(LAYER) if not e["type"].endswith("Point") and e["serial"] not in b]


def span(serial):
    v = rel(geom(serial)["points"])
    return [p[:2] for p in v]


def t_explode_lines():
    line = ln("LW_EXP", [(0, 0), (100, 0), (100, 50)])
    b = ents_before() - {line}
    open_cmd("anz_explodelines", select=[line])
    r = fill([["Every segment", True]], press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    parts = lines_now(b)
    spans = sorted(span(e["serial"]) for e in parts)
    ok = [(0, 0), (100, 0)] in spans and [(100, 0), (100, 50)] in spans
    record("Explode Lines", ok, "%d lines %s (A-B-C -> 2 segments); original kept: %s" % (len(parts), spans, any(e["serial"] == line for e in parts)), r)


def t_join():
    l1 = ln("LW_J1", [(0, 0), (50, 0)])
    l2 = ln("LW_J2", [(50, 0), (100, 0)])
    open_cmd("joinlines")
    r = fill([["Two lines", True], ["TwoPrimarySelectEntity", l1], ["TwoSecondarySelectEntity", l2]], press="Join", wait=2)
    S.run_ipy("command_ui", "close", {})
    left = [e["serial"] for e in entities(LAYER) if e["serial"] in (l1, l2)]
    s = span(left[0]) if left else []
    ok = len(left) == 1 and s[0] == (0, 0) and s[-1] == (100, 0)
    record("Join", ok, "lines left %s, joined span %s" % (left, s), r)


def t_clip():
    rect = rect_polyline("LW_CLIP_BND")
    line = ln("LW_CLIP", [(-20, 25), (120, 25)])
    b = ents_before() - {line}
    open_cmd("cliplines")
    r = fill([["Remove lines outside bounding lines", True], ["lineSelection", [line]], ["clippingBoundariesSelection", [rect]]], press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    now = [e for e in lines_now(b)]
    spans = sorted(span(e["serial"]) for e in now if e["serial"] != rect)
    ok = spans == [[(0, 25), (100, 25)]]
    record("Clip", ok, "remaining pieces %s (outside the rectangle removed)" % spans, r)


def t_set_line_elevation():
    # TBC refuses lines with 3D vertices ("Linestrings with 3D coordinates cannot be given a constant elevation"): 2D line
    line = make_line(LAYER, "LW_ELEV", [(E0, N0, None), (E0 + 100, N0, None)])
    open_cmd("setlineelevation")
    r = fill([["Line", line], ["Elevation", "25"]], press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    eff = S.t_get_entity({"serial": line})
    v = rel(geom(line)["points"])
    zs = [round(x.get("z"), 3) for x in eff.get("vertices", []) if x.get("z") is not None]
    ok = (zs and all(z == 25 for z in zs)) or all(p[2] == 25 for p in v)
    record("Set Line Elevation", ok, "polyseg z %s; get_entity vertices z %s (%s)" % ([p[2] for p in v], zs, eff.get("z_source")), r)
    if not ok:
        print("      get_entity:", json.dumps(eff, default=str)[:900])


def t_delete_segment():
    open_cmd("createlinestring")
    fill([["Name", "LW_DELSEG"], ["Layer", LAYER]], press="OK", wait=2)
    line = edit_linestring_vertices(["A", "B", "C"])
    S.pace_command()
    open_cmd("deletelinesegment")
    r = fill([["Line", line]])
    st = S.run_ipy("command_ui", "state", {})
    items = [f.get("options") for f in st["fields"] if f["kind"] == "list"][0]
    r = fill([["list", items[-1]]], press="Delete", wait=2)
    S.run_ipy("command_ui", "close", {})
    s = span(line)
    ok = len(s) == 2 and s[0] in ((0, 0), (100, 0))  # one of the two segments gone (the list showed the one deleted)
    record("Delete Segment", ok, "segments %s, deleted '%s' -> line now %s" % (items, items[-1], s), r)


def t_insert_segment():
    open_cmd("createlinestring")
    fill([["Name", "LW_INSSEG"], ["Layer", LAYER]], press="OK", wait=2)
    line = edit_linestring_vertices(["A", "B"])
    S.pace_command()
    open_cmd("standardinsertlinesegment", select=[line])
    st = S.run_ipy("command_ui", "state", {})
    r = fill([["Location", P["M"]]], press="Insert", wait=2)
    S.run_ipy("command_ui", "close", {})
    s = span(line)
    ok = (50, 50) in s and len(s) == 3
    record("Insert Segment", ok, "Line box '%s'; line now %s (vertex at M inserted)" % ([f.get("value") for f in st["fields"] if f["label"] == "Line"], s), r)


def t_divide_area():
    open_cmd("createpolygon")
    fill([["Name", "LW_DIVA"], ["Layer", LAYER]], press="OK", wait=2)
    poly = edit_linestring_vertices(["A", "B", "C", "D"])
    S.pace_command()
    b = ents_before() - {poly}
    open_cmd("dividearea")
    # order matters: link the area FIRST (WPF picker, by serial) and confirm it shows before any coordinate is typed
    r = fill([["Area to Divide", poly]])
    st = S.run_ipy("command_ui", "state", {})
    area_txt = [f.get("value") for f in st["fields"] if f["label"] == "Area to Divide"]
    if not area_txt or not str(area_txt[0]).strip():
        S.run_ipy("command_ui", "close", {})
        record("Divide Area", False, "Area to Divide did not take the polygon (%s); stopped before typing Origin" % area_txt, r)
        return
    r = fill([["Divide area based on", "Number of subareas"], ["Amount [min. 2]", "2"], ["Origin", P["A"]], ["End point", P["B"]]], press="Divide", wait=3)
    S.run_ipy("command_ui", "close", {})
    new = lines_now(b)
    areas = sorted(round(geom(e["serial"]).get("area") or 0, 1) for e in new)
    ok = len(new) >= 2
    record("Divide Area", ok, "Area box '%s'; %s new %s areas %s (100x50 into 2)" % (area_txt[0], len(new), [e["type"] for e in new], areas), r)
    for e in new:
        print("      piece", e["type"], rel(geom(e["serial"])["points"]))
    print("      original polygon still there:", any(e["serial"] == poly for e in entities(LAYER)))


def t_composite_geometry():
    l1 = ln("LW_CG1", [(0, 0), (50, 0)])
    l2 = ln("LW_CG2", [(50, 0), (100, 50)])
    b = ents_before()
    open_cmd("createcompositegeometry")  # the "Elements to add" box ignores a preselection: fill it with serials
    r = fill([["Name", "LW_COMP"], ["Layer", LAYER], ["Composite type", "Composite polyline"], ["Elements to add to composite", [l1, l2]]])
    r = click("Add", wait=1.5)
    r = click("Ok", wait=2)
    new = lines_now(b)
    s = span(new[0]["serial"]) if new else []
    ok = len(new) == 1 and s and s[0] == (0, 0) and s[-1] == (100, 50)
    record("Composite Geometry", ok, "%s span %s" % ([e["type"] for e in new], s), r)


def t_track_region():
    l1 = ln("LW_TR1", [(0, 0), (100, 0), (100, 50)])
    l2 = ln("LW_TR2", [(100, 50), (0, 50), (0, 0)])
    b = ents_before()
    open_cmd("trackregionoutline")
    r = fill([["Name", "LW_REG"], ["Layer", LAYER], ["m_LinesSelection", [l1, l2]], ["Reference point", P["IN"]]], press="Apply", wait=2)
    S.run_ipy("command_ui", "close", {})
    new = lines_now(b)
    g = geom(new[0]["serial"]) if new else {}
    corners = sorted(set((round(p[0]), round(p[1])) for p in rel(g.get("points", []))))
    ok = len(new) == 1 and corners == [(0, 0), (0, 50), (100, 0), (100, 50)]
    record("Track Region", ok, "%s corners %s" % ([e["type"] for e in new], corners), r)


def t_crossing_geometry():
    l1 = ln("LW_X1", [(0, 0), (100, 50)])
    l2 = make_line(LAYER, "LW_X2", [(E0, N0 + 50, 20), (E0 + 100, N0, 20)])
    open_cmd("crossinggeometry")
    r = fill([["memberSelection1", [l1, l2]]])
    st = S.run_ipy("command_ui", "state", {"include_text": True})
    r = click("Apply", wait=2)
    rows = S.run_ipy("command_ui", "grid_read", {}).get("rows", [])  # results table: one row per crossing
    click("Remove All Flags", wait=2)
    S.run_ipy("command_ui", "close", {})
    got = [(x["HigherGeometry"], x["LowerGeometry"], float(x["VerticalDifference"]), round(float(x["X"]) - E0, 2), round(float(x["Y"]) - N0, 2)) for x in rows]
    ok = len(got) == 1 and got[0][:3] == ("LW_X2", "LW_X1", 10.0)
    record("Detect Crossing Geometry", ok, "%s; crossings (higher, lower, dZ, dE, dN) %s; flags removed afterwards" % (st.get("texts"), got), r)


def t_append_tracked():
    base_l = ln("LW_AT_BASE", [(0, 0), (50, 0)])
    app = ln("LW_AT_APP", [(60, 0), (100, 0)])
    open_cmd("appendtrackedline")
    r = fill([["Base line", base_l], ["Line to append", app]], press="Append", wait=2)
    S.run_ipy("command_ui", "close", {})
    s = span(base_l) if any(e["serial"] == base_l for e in entities(LAYER)) else []
    ok = s and s[-1] == (100, 0)
    record("Append Tracked", ok, "base line now %s" % s, r)


TESTS = [t_polyline, t_circle, t_three_point_circle, t_arc, t_rectangle, t_three_point_rectangle,
         t_linestring, t_polygon, t_breakline, t_boundary, t_quick_line, t_best_fit_line,
         t_convert_to_linestring, t_offset, t_trim_extend, t_divide_lines, t_break,
         t_explode_lines, t_join, t_clip, t_set_line_elevation, t_delete_segment, t_insert_segment,
         t_composite_geometry, t_track_region, t_crossing_geometry, t_append_tracked, t_divide_area]
# Not run by default: Capture Outline and Fillet/Chamfer need picks in the Plan View
MANUAL = [t_outline, t_fillet]

if __name__ == "__main__":
    run(TESTS, sys.argv[1:], setup, lambda: None if "--keep" in sys.argv else cleanup([LAYER], surface_names=[SURF], base_forms=BASE_FORMS))
    json.dump({"results": __import__("tbc_testkit").results}, open("linework_results.json", "w"), indent=1)
