# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Shared helpers for live TBC command tests (paced, safe popups, numeric point IDs, cleanup)."""
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "mcp_server"))
import tbc_mcp_server as S  # noqa: E402

results = []


def record(name, ok, detail, r=None):
    results.append({"test": name, "ok": bool(ok), "detail": detail})
    print("%s %-26s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok and r is not None:
        print("      " + json.dumps(r, default=str)[:1200])


def close(a, b, tol=0.01):
    return all(abs(x - y) <= tol for x, y in zip(a, b) if x is not None and y is not None)


def base(offset_e=2000.0, offset_n=0.0):
    v = S.run_ipy("view", "info", {})
    return round(v["center"]["x"] + offset_e, 2), round(v["center"]["y"] + offset_n, 2)


def points(layer):
    return S.call_bridge("list_points", {"layer": layer, "limit": 2000})["points"]


def point(name):
    hits = [p for p in S.call_bridge("list_points", {"name_contains": str(name), "limit": 50})["points"] if p["name"] == str(name)]
    return hits[0] if hits else None


def entities(layer):
    return S.call_bridge("list_entities", {"layer": layer, "limit": 2000})["entities"]


def make_points(layer, coords, code=None):
    """coords: [(e, n, z|None)] -> list of {serial, name} with numeric IDs (user preference)."""
    pts = [{"easting": e, "northing": n, "layer": layer} for e, n, z in coords]
    for p, (_, _, z) in zip(pts, coords):
        if z is not None:
            p["elevation"] = z
        if code:
            p["feature_code"] = code
    r = S.t_create_points({"points": pts})
    if "points" in r:
        return r["points"]
    return [{"serial": point(i)["serial"], "name": i} for i in r["ids"]]


def make_line(layer, name, coords, closed=False):
    return S.call_bridge("create_linestring", {"name": name, "layer": layer, "closed": closed,
                                               "vertices": [{"x": x, "y": y, "z": z} for x, y, z in coords]})["serial"]


def open_cmd(key, select=None, confirm=False):
    S.call_bridge("set_selection", {"serials": select or []})
    return S.t_command_ui_open({"key": key, "confirm": confirm})


def fill(values, press=None, wait=1.5):
    return S.t_command_ui_fill({"values": values, "press": press, "wait_seconds": wait})


def click(button, wait=1.5, scope=None):
    return S.t_command_ui_click({"button": button, "wait_seconds": wait, "scope": scope})


def done():
    """Close panels/popups/new windows, clear selection (user preference: leave TBC tidy)."""
    S.safe_dismiss()
    try:
        S.run_ipy("command_ui", "close", {"all": True})
    except S.BridgeError:
        pass
    S.call_bridge("set_selection", {"serials": []})


def cleanup(layers, surface_names=(), base_forms=None):
    done()
    for nm in surface_names:
        for x in S.call_bridge("list_surfaces")["surfaces"]:
            if x["name"] == nm:
                S.t_delete_entities({"serials": [x["serial"]]})  # TBC's own Delete command
    for lay in layers:
        ser = sorted(set([e["serial"] for e in entities(lay)] + [p["serial"] for p in points(lay)]))
        if ser:
            try:
                S.t_delete_entities({"serials": ser})  # TBC's own Delete command
            except S.BridgeError as ex:
                print("cleanup: could not delete some objects on", lay, ex)
    # layers: TBC's Delete command with the layer selected (verified; the red-X click is unreliable in a narrow pane)
    lays = [l["serial"] for l in S.call_bridge("list_layers", {"with_counts": False})["layers"] if l["name"] in layers]
    if lays:
        try:
            S.t_delete_entities({"serials": lays})
        except S.BridgeError as ex:
            print("cleanup: could not delete layers", ex)
    if base_forms is not None:
        extra = [f["id"] for f in S.run_ipy("command_ui", "forms", {}) if f["id"] not in base_forms and not f["modal"]]
        if extra:
            S.run_ipy("command_ui", "close_forms", {"ids": extra})
    print("cleanup done; popups left:", S.dialogs_snapshot())


def run(tests, wanted, setup=None, teardown=None):
    if setup:
        setup()
    try:
        for t in tests:
            nm = t.__name__[2:]
            if wanted and nm not in wanted:
                continue
            log_size = os.path.getsize(S.ERROR_LOG) if os.path.exists(S.ERROR_LOG) else 0
            try:
                t()
            except Exception as ex:
                record(nm, False, "exception: %s" % str(ex)[:600])
            S.wait_idle()
            errs = [d for d in S.dialogs_snapshot() if S.is_error_dialog(d)]
            for d in errs:
                S.log_tbc_error(d, "test " + nm)
            if errs or (os.path.exists(S.ERROR_LOG) and os.path.getsize(S.ERROR_LOG) > log_size):
                print("STOPPING: TBC reported an error during '%s' (see %s). Leaving the popup for the user." % (nm, S.ERROR_LOG))
                for d in errs:
                    print("   ", d.get("title"), "|", (d.get("message") or "")[:800])
                return
            done()
            time.sleep(1.0)  # pacing between commands
    finally:
        if teardown and not [d for d in S.dialogs_snapshot() if S.is_error_dialog(d)]:
            teardown()
        print("\n%d/%d passed" % (sum(r["ok"] for r in results), len(results)))
