# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Usage pass for the CAD tab editing tools on throwaway objects (layer MCP_CADTEST*), checked numerically.
Every test: select targets -> command_ui_open -> fill -> press -> verify via the model -> close.
All test objects/layers are removed at the end. Usage: python cad_edit_tests.py [test names...]
"""
import json, math, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "mcp_server"))
import tbc_mcp_server as S

LAYER, LAYER2 = "MCP_CADTEST", "MCP_CADTEST2"
v = S.run_ipy("view", "info", {})
E0, N0 = round(v["center"]["x"] + 1000, 2), round(v["center"]["y"])
results = []
fx = {}


def verts(serial):
    return [(round(p["x"], 3), round(p["y"], 3), round(p["z"], 3) if p["z"] is not None else None)
            for p in S.t_get_entity({"serial": serial, "property_filter": "zzz"}).get("vertices", [])]


def on_layer(layer):
    return S.call_bridge("list_entities", {"layer": layer, "limit": 500})["entities"]


def make_line(name, pts):
    return S.call_bridge("create_linestring", {"name": name, "layer": LAYER, "vertices": [{"x": x, "y": y, "z": z} for x, y, z in pts]})["serial"]


def run_tool(key, select, values, press="Apply", wait=1.5):
    S.call_bridge("set_selection", {"serials": select})
    st = S.t_command_ui_open({"key": key})
    sel = [f["value"] for f in st.get("fields", []) if f.get("control") == "MemberSelection" or "Selected:" in str(f.get("value"))]
    r = S.t_command_ui_fill({"values": values, "press": press, "wait_seconds": wait})
    try:
        S.run_ipy("command_ui", "close", {"all": True})
    except S.BridgeError:
        pass
    S.call_bridge("set_selection", {"serials": []})
    return {"selection_field": sel, "fill": r}


def record(name, ok, detail, r=None):
    results.append({"test": name, "ok": ok, "detail": detail})
    print("%s %-22s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok and r is not None:
        print("      " + json.dumps(r)[:900])


def close(a, b, tol=0.01):
    return all(abs(x - y) <= tol for x, y in zip(a, b) if x is not None and y is not None)


# ---------------------------------------------------------------- fixtures
def setup():
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
    return make_line(name, [(E0, N0 + 200, 5), (E0 + 100, N0 + 200, 5), (E0 + 100, N0 + 300, 5)])


# ---------------------------------------------------------------- tests
def t_move():
    s = fresh_line("MOVE")
    before = verts(s)
    r = run_tool("moveobjects", [s], [["From", fx["TA"]], ["To", fx["TB"]]])
    after = verts(s)
    exp = [(x + 100, y, z) for x, y, z in before]
    record("Move", close(after[0], exp[0]) and close(after[-1], exp[-1]), "first vertex %s -> %s (expected +100 E)" % (before[0][:2], after[0][:2]), r)


def t_rotate():
    s = fresh_line("ROT")
    r = run_tool("rotateobjects", [s], [["Around", fx["TA"]], ["Angle", "90"]])
    a = verts(s)
    # +90 deg about TA: a vertex at (E0, N0+200) maps to either (E0+200, N0) [clockwise] or (E0-200, N0) [ccw]
    cw, ccw = (E0 + 200, N0), (E0 - 200, N0)
    ok = close(a[0][:2], cw) or close(a[0][:2], ccw)
    record("Rotate", ok, "vertex (E0, N0+200) -> %s; %s" % (a[0][:2], "clockwise" if close(a[0][:2], cw) else "counter-clockwise" if ok else "?"), r)


def t_scale():
    s = fresh_line("SCL")
    r = run_tool("scaleobjects", [s], [["From", fx["TA"]], ["Horizontal (X) scale", "2"]])
    a = verts(s)
    record("Scale", close(a[-1][:2], (E0 + 200, N0 + 600)), "last vertex -> %s (expected E0+200, N0+600)" % (a[-1][:2],), r)


def t_mirror():
    s = fresh_line("MIR")
    n_before = len(on_layer(LAYER))
    r = run_tool("mirrorobjects", [s], [["From", fx["TA"]], ["To", fx["TC"]]])
    new = [e for e in on_layer(LAYER) if e["type"].endswith("Linestring") and e["serial"] > s]
    ok = len(on_layer(LAYER)) == n_before + 1 and new
    mv = verts(new[0]["serial"]) if new else []
    ok = bool(ok) and bool(mv) and close(mv[1][:2], (E0 - 100, N0 + 200))
    record("Mirror", ok, "mirrored copy vertex 2 = %s (expected E0-100, N0+200); source kept: %s" % (mv[1][:2] if mv else None, bool(verts(s))), r)


def t_copy():
    s = fresh_line("CPY")
    n_before = len(on_layer(LAYER))
    r = run_tool("copyobjects", [s], [["Relayer copied objects", False]])
    n_after = len(on_layer(LAYER))
    record("Copy Objects", n_after == n_before + 1, "objects on layer %d -> %d" % (n_before, n_after), r)


def t_change_elev():
    s = fresh_line("ELV")
    r = run_tool("changeelevation", [s], [["Absolute elevation", True], ["m_NewElevation", "12.5"]])
    zs = [p[2] for p in verts(s)]
    record("Change Elevation", all(z is not None and abs(z - 12.5) < 0.01 for z in zs), "z values -> %s (expected 12.5)" % zs, r)


def t_relayer():
    s = fresh_line("RLY")
    r = run_tool("relayerobjects", [s], [["Target layer", LAYER2]])
    lay = S.call_bridge("get_entity", {"serial": s, "property_filter": "zzz"}).get("layer")
    record("Relayer Objects", lay == LAYER2, "layer -> %s (expected %s)" % (lay, LAYER2), r)


def t_name():
    s = fresh_line("UNNAMED")
    r = run_tool("nameobjects", [], [["Object to name", s], ["New name", "RENAMED_BY_MCP"]])
    nm = S.call_bridge("get_entity", {"serial": s, "property_filter": "zzz"}).get("name")
    record("Name Objects", nm == "RENAMED_BY_MCP", "name -> %s" % nm, r)


def make_poly3d(pts):
    code = ("from Trimble.Vce.ForeignCad import Poly3D\n"
            "f = bridge.factor(prj)\n"
            "p = wv.Add(clr.GetClrType(Poly3D))\n"
            "for x, y, z in args:\n"
            "    p.Append(Point3D(x / f, y / f, z / f))\n"
            "p.Layer = Layer.FindOrCreateLayer(prj, %r).SerialNumber\n"
            "result = int(p.SerialNumber)\n") % LAYER
    code = "args = %r\n" % (pts,) + code
    return S.call_bridge("execute_python", {"code": code})["result"]


def t_explode():
    # Never create CAD entities through raw API (crash on 2026-10-13). Instead copy an existing CAD polyline
    # with TBC's own Copy Objects command onto the test layer, then explode the copy. The original is untouched.
    src = S.call_bridge("list_entities", {"type_contains": "ForeignCad.BlockReference", "limit": 1})["entities"]
    if not src:
        record("Explode", False, "no block reference in the project to copy")
        return
    src = src[0]["serial"]
    before_all = set(e["serial"] for e in S.call_bridge("list_entities", {"type_contains": "ForeignCad", "limit": 100000})["entities"])
    r0 = run_tool("copyobjects", [src], [["Relayer copied objects", False]])
    copies = [e for e in S.call_bridge("list_entities", {"type_contains": "ForeignCad", "limit": 100000})["entities"] if e["serial"] not in before_all]
    if len(copies) != 1:
        record("Explode", False, "copy step produced %d new CAD objects" % len(copies), r0)
        for c in copies:
            S.call_bridge("delete_entities", {"serials": [c["serial"]]})
        return
    s = copies[0]["serial"]
    S.call_bridge("set_properties", {"serial": s, "properties": {"Layer": LAYER}})
    n_before = len(on_layer(LAYER))
    r = run_tool("explode", [s], [], press="Explode")
    ents = on_layer(LAYER)
    still = any(e["serial"] == s for e in ents)
    record("Explode", not still and len(ents) > n_before - 1, "source gone: %s; objects on layer %d -> %d; types %s" % (
        not still, n_before, len(ents), sorted(set(e["type"] for e in ents))), r)


def t_intervals():
    s = fresh_line("INT")
    before = S.call_bridge("list_points", {"layer": LAYER})["total_matched"]
    r = run_tool("createatinterval", [s], [["Selection", True], ["Interval", "25"], ["Starting point ID", "INT1"], ["Layer", LAYER]])
    after = S.call_bridge("list_points", {"layer": LAYER})["total_matched"]
    record("Create at Intervals", after > before, "points on layer %d -> %d (200 ft line @ 25 ft -> ~9)" % (before, after), r)


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
    r = run_tool("drapeobjectsonsurface", [], [["Surface", surf[0]["serial"]], ["ReferenceLineSelectEntity", s], ["Layer", LAYER]])
    ents = on_layer(LAYER)
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


TESTS = [t_move, t_rotate, t_scale, t_mirror, t_copy, t_change_elev, t_relayer, t_name, t_explode, t_intervals, t_drape]


def cleanup():
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
            acts = S.safe_dismiss()
            if acts:
                print("      dismissed:", acts)
                if any(a.get("still_open") for a in acts):
                    print("ABORT: popups could not be closed safely")
                    break
    finally:
        cleanup()
        json.dump(results, open(os.path.join(here, "cad_edit_results.json"), "w"), indent=1)
        print("\n%d/%d passed" % (sum(r["ok"] for r in results), len(results)))



