# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Usage pass for the CAD tab editing tools on throwaway objects (layer MCP_CADTEST*), checked numerically.
Every test: select targets -> command_ui_open -> fill -> press -> verify via the model -> close.
All test objects/layers are removed at the end. Usage: python cad_edit_tests.py [test names...]

Needs TBC
    Yes: TBC 2026.10 running, a project open (use a copy) and the MCP Bridge macro switched on. The module
    talks to TBC as soon as it is imported (it reads the Plan View centre at the top level).
    The Explode test also needs at least one CAD block reference (ForeignCad.BlockReference) already in the
    project to copy; without one it records a FAIL.

How to run
    py -3.12 tests\\cad_edit_tests.py                 all tests
    py -3.12 tests\\cad_edit_tests.py move rotate     only t_move and t_rotate (names without the "t_" prefix)

What it creates and cleans up
    Layers MCP_CADTEST and MCP_CADTEST2, three fixture points (next free numeric IDs) 1000 display units east
    of the Plan View centre, one short linestring per test, a 5 x 5 grid of points and a flat surface
    MCP_DRAPE_TEST for the drape test, and a copy of one block reference for the explode test.
    cleanup() always runs (finally block): it deletes the surface, every object and point on both layers and
    then the layers themselves.

What it writes
    tests\\cad_edit_results.json (list of {"test", "ok", "detail"}; ignored by git via tests/*_results.json).

Pass / fail
    Each test records one PASS/FAIL line from the model geometry read back after the command (vertex
    coordinates within 0.01, layer, name, object counts). The run stops early ("ABORT") if a popup could not
    be closed safely. The last line prints "N/M passed"; FAILs do not change the exit code (read the output
    or the JSON file).

Note: this suite predates tests\\tbc_testkit.py and has its own copies of record(), close() and the run loop.
Its cleanup and the explode test delete through the bridge's raw "delete_entities" method (container
removal), not through the server's delete_entities tool (TBC's own Delete command) that the other suites use.
"""
import json, math, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
# import the MCP server module in-process so the tests use its guardrails (pacing, waits, safe popups)
sys.path.insert(0, os.path.join(here, "..", "mcp_server"))
import tbc_mcp_server as S

LAYER, LAYER2 = "MCP_CADTEST", "MCP_CADTEST2"
# fixture origin: 1000 display units east of the current Plan View centre, away from the user's work
v = S.run_ipy("view", "info", {})
E0, N0 = round(v["center"]["x"] + 1000, 2), round(v["center"]["y"])
results = []
# fixtures made by setup(): aliases TA/TB/TC -> point IDs, "<alias>_serial" -> serials, "surface_serial"
fx = {}


def verts(serial):
    """Vertices of a linestring as (x, y, z) rounded to 3 decimals; z None when undefined.

    Uses the server's get_entity tool (S.t_get_entity), which fills in effective elevations from the
    vertical profile when TBC stores them there (e.g. after Change Elevation).
    property_filter "zzz" matches no property name, so only the geometry comes back.
    """
    return [(round(p["x"], 3), round(p["y"], 3), round(p["z"], 3) if p["z"] is not None else None)
            for p in S.t_get_entity({"serial": serial, "property_filter": "zzz"}).get("vertices", [])]


def on_layer(layer):
    """Non-point objects on a layer (bridge list_entities, capped at 500)."""
    return S.call_bridge("list_entities", {"layer": layer, "limit": 500})["entities"]


def make_line(name, pts):
    """Create a linestring on LAYER through the bridge API from [(x, y, z)]; returns its serial."""
    return S.call_bridge("create_linestring", {"name": name, "layer": LAYER, "vertices": [{"x": x, "y": y, "z": z} for x, y, z in pts]})["serial"]


def run_tool(key, select, values, press="Apply", wait=1.5):
    """Run one CAD command the way a user would: select, open the panel, fill, press, close.

    key     TBC command key (e.g. "moveobjects")
    select  serials to pre-select (the panel's selection box picks them up), or []
    values  [[field label or id, value], ...] for command_ui_fill
    press   button pressed after filling (default "Apply")
    Returns {"selection_field": what the panel's selection box showed, "fill": the fill result}, used as
    the debugging dump when a check fails.
    """
    S.call_bridge("set_selection", {"serials": select})
    st = S.t_command_ui_open({"key": key})
    # the panel's member-selection box (shows e.g. "Selected: 1") proves the pre-selection was taken
    sel = [f["value"] for f in st.get("fields", []) if f.get("control") == "MemberSelection" or "Selected:" in str(f.get("value"))]
    r = S.t_command_ui_fill({"values": values, "press": press, "wait_seconds": wait})
    try:
        S.run_ipy("command_ui", "close", {"all": True})
    except S.BridgeError:
        pass
    S.call_bridge("set_selection", {"serials": []})
    return {"selection_field": sel, "fill": r}


def record(name, ok, detail, r=None):
    """Record and print one result (local copy of tbc_testkit.record; dumps `r` on failure)."""
    results.append({"test": name, "ok": ok, "detail": detail})
    print("%s %-22s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok and r is not None:
        print("      " + json.dumps(r)[:900])


def close(a, b, tol=0.01):
    """Coordinates equal within `tol`, skipping None components (local copy of tbc_testkit.close)."""
    return all(abs(x - y) <= tol for x, y in zip(a, b) if x is not None and y is not None)


# ---------------------------------------------------------------- fixtures
def setup():
    """Create both test layers and three fixture points at elevation 10.

    TA at (E0, N0), TB 100 east of it, TC 100 north of it. Their numeric IDs are typed into the panels'
    coordinate boxes (From / To / Around), so moves and mirrors have known reference points.
    """
    try:
        S.run_ipy("command_ui", "close", {"all": True})
    except S.BridgeError:
        pass
    S.call_bridge("create_layer", {"name": LAYER})
    S.call_bridge("create_layer", {"name": LAYER2})
    # user preference: numeric point IDs (next free numbers); TA/TB/TC are just local aliases
    r = S.t_create_points({"points": [
        {"easting": E0, "northing": N0, "elevation": 10, "layer": LAYER},
        {"easting": E0 + 100, "northing": N0, "elevation": 10, "layer": LAYER},
        {"easting": E0, "northing": N0 + 100, "elevation": 10, "layer": LAYER}]})
    for alias, p in zip(("TA", "TB", "TC"), r["points"]):
        fx[alias] = p["name"]
        fx[alias + "_serial"] = p["serial"]
    print("fixtures at E %.2f N %.2f: %s" % (E0, N0, fx))


def fresh_line(name="L1"):
    """A new 3-vertex test linestring at z 5: (E0, N0+200) -> (E0+100, N0+200) -> (E0+100, N0+300)."""
    return make_line(name, [(E0, N0 + 200, 5), (E0 + 100, N0 + 200, 5), (E0 + 100, N0 + 300, 5)])


# ---------------------------------------------------------------- tests
# Move Objects (moveobjects): From TA To TB must shift every vertex exactly 100 east.
def t_move():
    s = fresh_line("MOVE")
    before = verts(s)
    r = run_tool("moveobjects", [s], [["From", fx["TA"]], ["To", fx["TB"]]])
    after = verts(s)
    exp = [(x + 100, y, z) for x, y, z in before]
    record("Move", close(after[0], exp[0]) and close(after[-1], exp[-1]), "first vertex %s -> %s (expected +100 E)" % (before[0][:2], after[0][:2]), r)


# Rotate Objects (rotateobjects): 90 degrees around TA. TBC's rotation direction wasn't assumed, so either
# direction passes; the detail line says which one TBC used.
def t_rotate():
    s = fresh_line("ROT")
    r = run_tool("rotateobjects", [s], [["Around", fx["TA"]], ["Angle", "90"]])
    a = verts(s)
    # +90 deg about TA: a vertex at (E0, N0+200) maps to either (E0+200, N0) [clockwise] or (E0-200, N0) [ccw]
    cw, ccw = (E0 + 200, N0), (E0 - 200, N0)
    ok = close(a[0][:2], cw) or close(a[0][:2], ccw)
    record("Rotate", ok, "vertex (E0, N0+200) -> %s; %s" % (a[0][:2], "clockwise" if close(a[0][:2], cw) else "counter-clockwise" if ok else "?"), r)


# Scale Objects (scaleobjects): factor 2 from TA. Only "Horizontal (X) scale" is filled, yet the expected last
# vertex (E0+200, N0+600) is the original (E0+100, N0+300) doubled in both X and Y.
def t_scale():
    s = fresh_line("SCL")
    r = run_tool("scaleobjects", [s], [["From", fx["TA"]], ["Horizontal (X) scale", "2"]])
    a = verts(s)
    record("Scale", close(a[-1][:2], (E0 + 200, N0 + 600)), "last vertex -> %s (expected E0+200, N0+600)" % (a[-1][:2],), r)


# Mirror Objects (mirrorobjects): mirror line TA -> TC (the north-south line x = E0). Expects exactly one new
# linestring (a mirrored copy, newest serial) whose 2nd vertex is (E0-100, N0+200), with the source kept.
def t_mirror():
    s = fresh_line("MIR")
    n_before = len(on_layer(LAYER))
    r = run_tool("mirrorobjects", [s], [["From", fx["TA"]], ["To", fx["TC"]]])
    new = [e for e in on_layer(LAYER) if e["type"].endswith("Linestring") and e["serial"] > s]
    ok = len(on_layer(LAYER)) == n_before + 1 and new
    mv = verts(new[0]["serial"]) if new else []
    ok = bool(ok) and bool(mv) and close(mv[1][:2], (E0 - 100, N0 + 200))
    record("Mirror", ok, "mirrored copy vertex 2 = %s (expected E0-100, N0+200); source kept: %s" % (mv[1][:2] if mv else None, bool(verts(s))), r)


# Copy Objects (copyobjects) with "Relayer copied objects" off: one more object on the test layer.
def t_copy():
    s = fresh_line("CPY")
    n_before = len(on_layer(LAYER))
    r = run_tool("copyobjects", [s], [["Relayer copied objects", False]])
    n_after = len(on_layer(LAYER))
    record("Copy Objects", n_after == n_before + 1, "objects on layer %d -> %d" % (n_before, n_after), r)


# Change Elevation (changeelevation), absolute 12.5: every vertex's effective z must read 12.5.
# "m_NewElevation" is the elevation box's control id (it is filled by id, not by label).
def t_change_elev():
    s = fresh_line("ELV")
    r = run_tool("changeelevation", [s], [["Absolute elevation", True], ["m_NewElevation", "12.5"]])
    zs = [p[2] for p in verts(s)]
    record("Change Elevation", all(z is not None and abs(z - 12.5) < 0.01 for z in zs), "z values -> %s (expected 12.5)" % zs, r)


# Relayer Objects (relayerobjects): the line must end up on MCP_CADTEST2.
def t_relayer():
    s = fresh_line("RLY")
    r = run_tool("relayerobjects", [s], [["Target layer", LAYER2]])
    lay = S.call_bridge("get_entity", {"serial": s, "property_filter": "zzz"}).get("layer")
    record("Relayer Objects", lay == LAYER2, "layer -> %s (expected %s)" % (lay, LAYER2), r)


# Name Objects (nameobjects): nothing pre-selected; the object is given to the panel's "Object to name"
# picker by serial, then renamed.
def t_name():
    s = fresh_line("UNNAMED")
    r = run_tool("nameobjects", [], [["Object to name", s], ["New name", "RENAMED_BY_MCP"]])
    nm = S.call_bridge("get_entity", {"serial": s, "property_filter": "zzz"}).get("name")
    record("Name Objects", nm == "RENAMED_BY_MCP", "name -> %s" % nm, r)


def make_poly3d(pts):
    """Create a CAD Poly3D on LAYER directly through the API (execute_python); returns its serial.

    pts are [(x, y, z)] in display units; dividing by bridge.factor(prj) converts them to the project's
    internal units. Not called by any test: t_explode's comment says creating CAD entities through the raw
    API crashed TBC on 2026-10-13, so the explode test copies an existing block reference instead.
    """
    code = ("from Trimble.Vce.ForeignCad import Poly3D\n"
            "f = bridge.factor(prj)\n"
            "p = wv.Add(clr.GetClrType(Poly3D))\n"
            "for x, y, z in args:\n"
            "    p.Append(Point3D(x / f, y / f, z / f))\n"
            "p.Layer = Layer.FindOrCreateLayer(prj, %r).SerialNumber\n"
            "result = int(p.SerialNumber)\n") % LAYER
    code = "args = %r\n" % (pts,) + code
    return S.call_bridge("execute_python", {"code": code})["result"]


# Explode (explode) on a copy of an existing block reference moved onto the test layer: the copy must be gone
# afterwards and the layer must hold at least as many objects as before (the exploded parts).
def t_explode():
    # Never create CAD entities through raw API (crash on 2026-10-13). Instead copy an existing CAD polyline
    # with TBC's own Copy Objects command onto the test layer, then explode the copy. The original is untouched.
    src = S.call_bridge("list_entities", {"type_contains": "ForeignCad.BlockReference", "limit": 1})["entities"]
    if not src:
        record("Explode", False, "no block reference in the project to copy")
        return
    src = src[0]["serial"]
    # snapshot every CAD object's serial so the copy made next can be told apart from what was there
    before_all = set(e["serial"] for e in S.call_bridge("list_entities", {"type_contains": "ForeignCad", "limit": 100000})["entities"])
    r0 = run_tool("copyobjects", [src], [["Relayer copied objects", False]])
    copies = [e for e in S.call_bridge("list_entities", {"type_contains": "ForeignCad", "limit": 100000})["entities"] if e["serial"] not in before_all]
    if len(copies) != 1:
        record("Explode", False, "copy step produced %d new CAD objects" % len(copies), r0)
        # remove whatever the copy produced (bridge raw delete, not TBC's Delete command)
        for c in copies:
            S.call_bridge("delete_entities", {"serials": [c["serial"]]})
        return
    s = copies[0]["serial"]
    # move the copy onto the test layer so cleanup() removes it and its exploded parts
    S.call_bridge("set_properties", {"serial": s, "properties": {"Layer": LAYER}})
    n_before = len(on_layer(LAYER))
    r = run_tool("explode", [s], [], press="Explode")
    ents = on_layer(LAYER)
    still = any(e["serial"] == s for e in ents)
    record("Explode", not still and len(ents) > n_before - 1, "source gone: %s; objects on layer %d -> %d; types %s" % (
        not still, n_before, len(ents), sorted(set(e["type"] for e in ents))), r)


# Create at Intervals (createatinterval): points every 25 along the selected line, IDs starting INT1, on the
# test layer. Passes when the layer gained any points (the exact count isn't checked).
def t_intervals():
    s = fresh_line("INT")
    before = S.call_bridge("list_points", {"layer": LAYER})["total_matched"]
    r = run_tool("createatinterval", [s], [["Selection", True], ["Interval", "25"], ["Starting point ID", "INT1"], ["Layer", LAYER]])
    after = S.call_bridge("list_points", {"layer": LAYER})["total_matched"]
    record("Create at Intervals", after > before, "points on layer %d -> %d (200 ft line @ 25 ft -> ~9)" % (before, after), r)


# Drape Objects on Surface (drapeobjectsonsurface): first builds a flat surface MCP_DRAPE_TEST at z 0 from a
# 5 x 5 grid of points with Create Surface (surfacecreate), then drapes a z-5 line onto it. Passes when every
# resulting elevation is 0 (within 0.01), whether TBC made a new object or changed the line in place.
def t_drape():
    # build a small flat test surface (z = 0) 600 ft north of the fixtures with verified tools only
    gx, gy = E0, N0 + 600
    g = S.t_create_points({"points": [{"easting": gx + i * 50, "northing": gy + j * 50, "elevation": 0, "layer": LAYER}
                                      for i in range(5) for j in range(5)]})
    S.call_bridge("set_selection", {"serials": [p["serial"] for p in g["points"]]})
    S.t_command_ui_open({"key": "surfacecreate"})
    S.t_command_ui_fill({"values": [["Name", "MCP_DRAPE_TEST"]], "press": "OK", "wait_seconds": 2})
    S.call_bridge("set_selection", {"serials": []})
    surf = [x for x in S.call_bridge("list_surfaces")["surfaces"] if x["name"] == "MCP_DRAPE_TEST"]
    if not surf:
        record("Drape on Surface", False, "could not build the test surface")
        return
    fx["surface_serial"] = surf[0]["serial"]
    s = make_line("DRP", [(gx + 25, gy + 100, 5), (gx + 175, gy + 100, 5)])
    n_before = len(on_layer(LAYER))
    # "ReferenceLineSelectEntity" is the line picker's control id; pickers take serials
    r = run_tool("drapeobjectsonsurface", [], [["Surface", surf[0]["serial"]], ["ReferenceLineSelectEntity", s], ["Layer", LAYER]])
    ents = on_layer(LAYER)
    # serials grow, so anything newer than the line was made by the drape
    new = [e for e in ents if e["serial"] > s]
    targets = [e["serial"] for e in new] or [s]  # drape may create a new object or change the line in place
    zs = [p[2] for t in targets for p in verts(t)]
    if new and not zs:
        # not a linestring: sample the new object's geometry through its polyseg
        code = ("o = bridge.lookup(prj, %d)\nf = bridge.factor(prj)\nps = o.ComputePolySeg()\n"
                "pts = list(ps.ToPoint3DArray()) if hasattr(ps, 'ToPoint3DArray') else []\n"
                "result = {'type': o.GetType().FullName, 'z': [p.Z * f for p in pts][:12]}") % new[0]["serial"]
        try:
            info = S.call_bridge("execute_python", {"code": code, "transaction": False})["result"]
        except S.BridgeError as ex:
            info = {"type": new[0]["type"], "z": [], "error": str(ex)[:200]}
        print("      new object:", info)
        zs = info.get("z") or []
    ok = bool(zs) and all(z is not None and abs(z) < 0.01 for z in zs)
    record("Drape on Surface", ok, "%s; z %s (surface flat at 0, line was at 5)" % (
        "new object(s)" if new else "line changed in place", zs[:8]), r)


# run order; command-line names select from this list (function name without "t_")
TESTS = [t_move, t_rotate, t_scale, t_mirror, t_copy, t_change_elev, t_relayer, t_name, t_explode, t_intervals, t_drape]


def cleanup():
    """Close panels, clear the selection, then delete MCP_DRAPE_TEST, everything on both test layers and the
    layers themselves. Uses the bridge's raw delete_entities method (see the module note). Prints leftover
    popups."""
    try:
        S.run_ipy("command_ui", "close", {"all": True})
    except S.BridgeError:
        pass
    S.call_bridge("set_selection", {"serials": []})
    for x in S.call_bridge("list_surfaces")["surfaces"]:
        if x["name"] == "MCP_DRAPE_TEST":
            S.call_bridge("delete_entities", {"serials": [x["serial"]]})
    for lay in (LAYER, LAYER2):
        ents = on_layer(lay)
        pts = S.call_bridge("list_points", {"layer": lay, "limit": 1000})["points"]
        ser = sorted(set([e["serial"] for e in ents] + [p["serial"] for p in pts]))
        if ser:
            S.call_bridge("delete_entities", {"serials": ser})
    for l in S.call_bridge("list_layers", {"with_counts": False})["layers"]:
        if l["name"] in (LAYER, LAYER2):
            S.call_bridge("delete_entities", {"serials": [l["serial"]]})
    left = S.dialogs_snapshot()
    print("cleanup done; leftover popups:", left)


if __name__ == "__main__":
    wanted = sys.argv[1:]
    setup()
    try:
        for t in TESTS:
            if wanted and t.__name__[2:] not in wanted:
                continue
            try:
                t()
            except Exception as ex:
                record(t.__name__[2:], False, "exception: %s" % str(ex)[:500])
            # after each test close any popup the safe way (Cancel/Close/No or X); if one stays open, stop
            acts = S.safe_dismiss()
            if acts:
                print("      dismissed:", acts)
                if any(a.get("still_open") for a in acts):
                    print("ABORT: popups could not be closed safely")
                    break
    finally:
        # always clean up and save results, even after an abort or a crash in a test
        cleanup()
        json.dump(results, open(os.path.join(here, "cad_edit_results.json"), "w"), indent=1)
        print("\n%d/%d passed" % (sum(r["ok"] for r in results), len(results)))



