# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Shared helpers for live TBC command tests (paced, safe popups, numeric point IDs, cleanup).

What this is
    Not a test itself: a small library imported by the live usage suites in tests/ (cad_edit_tests.py,
    survey_cogo_tests.py, linework_tests.py, drafting_tests.py, home_tests.py, selection_tests.py).
    It imports the MCP server module (mcp_server/tbc_mcp_server.py) directly as `S` and calls its functions
    in-process, so the suites use exactly the same guardrails an AI client gets through MCP (license check,
    paced command launches, wait for Compute Project, safe popup handling, TBC's own Delete command).

Needs TBC
    Yes. Every helper except record() and close() talks to the bridge macro, so TBC must be running with a
    project open and Macros > MCP > MCP Bridge switched on (green). The bridge is found through the info file
    (TBC_MCP_INFO, default %TEMP%\\tbc_mcp_bridge.json), like the server does.

How a suite uses it
    A suite defines functions named t_<name>(), each of which calls record(name, ok, detail) one or more
    times, then hands the list to run(tests, wanted, setup, teardown). run() executes them in order, stops
    the whole suite when TBC shows an error report, tidies up after each test with done(), and prints
    "N/M passed" at the end. Suites call cleanup() from their teardown to delete the throwaway layers,
    surfaces and windows they made.

Pass / fail
    A test passes when every record() call for it had ok=True. Results are collected in the module-level
    `results` list (home, selection, linework and drafting dump it to <suite>_results.json in the current
    directory; survey_cogo writes none); nothing here writes files
    except that TBC error popups are appended to S.ERROR_LOG (knowledge/memory/tbc_errors.log) by the server.
"""
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
# make mcp_server/ importable so the server module (and its knowledge/projects/tbc_help imports) load in-process
sys.path.insert(0, os.path.join(here, "..", "mcp_server"))
import tbc_mcp_server as S  # noqa: E402

# every record() call appends {"test", "ok", "detail"} here; suites read it for the summary and their JSON result file
results = []


def record(name, ok, detail, r=None):
    """Record one check result and print a PASS/FAIL line.

    name   short test name (column-aligned in the output)
    ok     truthy for pass
    detail human-readable evidence (measured values, counts)
    r      optional raw tool result; printed (first 1200 chars of its JSON) only on failure, to help debugging
    """
    results.append({"test": name, "ok": bool(ok), "detail": detail})
    print("%s %-26s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok and r is not None:
        print("      " + json.dumps(r, default=str)[:1200])


def close(a, b, tol=0.01):
    """True when two coordinate sequences agree within `tol` (project display units) component by component.

    Components that are None on either side (for example an undefined elevation) are skipped, so
    close((x, y, None), (x, y, 5.0)) is True. zip() stops at the shorter sequence.
    """
    return all(abs(x - y) <= tol for x, y in zip(a, b) if x is not None and y is not None)


def base(offset_e=2000.0, offset_n=0.0):
    """Pick a working origin (easting, northing) for throwaway test objects.

    Reads the centre of TBC's current Plan View (ipy/view.py action "info") and shifts it by the offsets,
    by default 2000 display units east, so the test geometry lands away from whatever the user is looking at.
    Rounded to 2 decimals so expected coordinates in the checks are easy to compare.
    """
    v = S.run_ipy("view", "info", {})
    return round(v["center"]["x"] + offset_e, 2), round(v["center"]["y"] + offset_n, 2)


def points(layer):
    """All points on one layer (bridge list_points, capped at 2000)."""
    return S.call_bridge("list_points", {"layer": layer, "limit": 2000})["points"]


def point(name):
    """The point whose ID is exactly `name`, or None.

    list_points only filters by substring (name_contains), so the hits are narrowed to an exact match here.
    """
    hits = [p for p in S.call_bridge("list_points", {"name_contains": str(name), "limit": 50})["points"] if p["name"] == str(name)]
    return hits[0] if hits else None


def entities(layer):
    """All non-point objects reported by the bridge's list_entities on one layer (capped at 2000)."""
    return S.call_bridge("list_entities", {"layer": layer, "limit": 2000})["entities"]


def make_points(layer, coords, code=None):
    """coords: [(e, n, z|None)] -> list of {serial, name} with numeric IDs (user preference).

    Goes through the server's create_points tool (S.t_create_points), which picks the next free numeric IDs.
    Without a feature code that is one API call; with `code` the server types every point into TBC's
    Create Point panel instead (so TBC's own code processing runs), which is much slower.
    """
    pts = [{"easting": e, "northing": n, "layer": layer} for e, n, z in coords]
    for p, (_, _, z) in zip(pts, coords):
        if z is not None:
            p["elevation"] = z
        if code:
            p["feature_code"] = code
    r = S.t_create_points({"points": pts})
    # the API path returns "points" with serials; the Create Point panel path returns only the "ids" it typed,
    # so each serial is looked up by its point ID
    if "points" in r:
        return r["points"]
    return [{"serial": point(i)["serial"], "name": i} for i in r["ids"]]


def make_line(layer, name, coords, closed=False):
    """Create a linestring through the bridge API from [(x, y, z)] vertices; returns its serial."""
    return S.call_bridge("create_linestring", {"name": name, "layer": layer, "closed": closed,
                                               "vertices": [{"x": x, "y": y, "z": z} for x, y, z in coords]})["serial"]


def open_cmd(key, select=None, confirm=False):
    """Select `select` (list of serials, or nothing) and open command `key`'s panel.

    Uses the server's command_ui_open (S.t_command_ui_open), so the license check, the known-danger
    confirm gate, the wait for Compute Project, the 2.5 s launch pacing and the wait for the panel to stop
    changing all apply. Returns the panel description (fields, buttons, open command).
    Pass confirm=True for commands the server knows act immediately or open a web page.
    """
    S.call_bridge("set_selection", {"serials": select or []})
    return S.t_command_ui_open({"key": key, "confirm": confirm})


def fill(values, press=None, wait=1.5):
    """Fill fields in the open panel (server command_ui_fill) and optionally press a button afterwards.

    values  dict or list of [label/id, value] pairs (coordinate boxes take point IDs, pickers take serials)
    press   button text to press after filling (e.g. "Apply"), or None
    wait    seconds to wait after the press before the server reads back popups and field status messages
    """
    return S.t_command_ui_fill({"values": values, "press": press, "wait_seconds": wait})


def click(button, wait=1.5, scope=None):
    """Press a button or select a tab in the open panel (server command_ui_click).

    scope   None for the command panel, or e.g. "dialog:<index>" for a popup
    The result carries "after": open command, popups and field status messages `wait` seconds later.
    """
    return S.t_command_ui_click({"button": button, "wait_seconds": wait, "scope": scope})


def done():
    """Close panels/popups/new windows, clear selection (user preference: leave TBC tidy).

    S.safe_dismiss() only ever presses Cancel/Close/No/Abort or closes a popup with X, and never touches a
    progress window. Run after every test by run().
    """
    S.safe_dismiss()
    try:
        S.run_ipy("command_ui", "close", {"all": True})
    except S.BridgeError:
        # nothing open to close, or the panel had already gone: not a test failure
        pass
    S.call_bridge("set_selection", {"serials": []})


def cleanup(layers, surface_names=(), base_forms=None):
    """Delete everything a suite made, always through TBC's own Delete command.

    layers         names of the throwaway layers: every point and object on them is deleted, then the layers
    surface_names  surfaces to delete by exact name (surfaces may sit on another layer)
    base_forms     ids of the non-modal windows that were open before the suite started (from
                   ipy/command_ui.py action "forms"); any other non-modal window left open is closed.
                   None skips this step.
    Failures are printed, not raised, so one stuck object doesn't stop the rest of the cleanup. Prints the
    popups still open at the end.
    """
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
    """Run a suite's test functions in order with the safety rules shared by every live suite.

    tests     list of functions named t_<name>; <name> (the "t_" prefix stripped) is the test name
    wanted    names to run (usually sys.argv[1:]); empty runs all
    setup     called once before the first test (e.g. create the throwaway layer and base points)
    teardown  called once at the end (usually cleanup()), but skipped when a TBC error popup is still open,
              so the user can read it
    After each test: wait for Compute Project, then stop the whole suite if TBC showed an error report
    (a new error popup, or new lines in S.ERROR_LOG during the test); otherwise tidy up with done() and pause
    one second. An exception inside a test is recorded as a FAIL and the suite carries on.
    Prints "N/M passed" (counting record() calls, not test functions) at the end.
    """
    if setup:
        setup()
    try:
        for t in tests:
            nm = t.__name__[2:]
            if wanted and nm not in wanted:
                continue
            # remember the error log's size so an error logged during this test (by the server's popup
            # handling) can be noticed even when the popup itself has already been closed
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
