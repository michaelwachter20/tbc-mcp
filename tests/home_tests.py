# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Live usage tests for the Home tab's Import and Export (the user's scope for this tab), through the MCP tools
tbc_export / tbc_import. Throwaway points/lines on layer MCP_HOMETEST; exported files go to tests\\mcp_export_tmp
(never the project folder) and are checked, then deleted. Never uses Remote Save / Connected Workspace (online).
Import copies each imported file into the project folder: the user chose to leave those copies (names reported).
py -3.12 home_tests.py [names]

Needs TBC
    Yes: TBC 2026.10 with a project open (use a copy: imports leave records and file copies in it) and the
    MCP Bridge macro on. The module talks to TBC at import time. Uses tests\\tbc_testkit.py.

How to run
    cd tests
    py -3.12 home_tests.py                          all tests in TESTS
    py -3.12 home_tests.py export_csv import_csv    only these (function names without "t_")
    py -3.12 home_tests.py export_csv --keep        skip the teardown (leave layer, objects and temp folders);
                                                    "--keep" also counts as a test name, so give real names too
    Run from tests\\ so home_results.json lands where .gitignore expects it (it is written to the current
    directory). Import DXF needs the file written by Export DXF in the same run.

What it creates and cleans up
    Layer MCP_HOMETEST with three coded points (code MCPX, via the Create Point panel) and one linestring,
    3000 east / 1200 north of the Plan View centre; folders tests\\mcp_export_tmp and tests\\mcp_import_tmp
    (emptied at setup). The imports add points 4790001/4790002 (code MCPIMP) and DXF linework, which the
    tests delete again; the import records (FileProperties) are deliberately left, see remove_import().
    The teardown deletes the layer's contents, the layer, leftover windows and both temp folders.

What it writes
    home_results.json in the current directory ({"results": [...]}); exported files in mcp_export_tmp
    (deleted by the teardown).

Pass / fail
    Export: the file exists and has the expected content (CSV rows with our point IDs and code, a DXF over
    500 bytes with POLYLINE, LandXML with all three point IDs). Import: the scan lists the CSV; imported
    points/objects appear where expected. "N/M passed" at the end; FAILs don't change the exit code.
"""
import json, os, shutil, sys
from tbc_testkit import S, record, base, entities, make_points, make_line, cleanup, run, point

LAYER = "MCP_HOMETEST"
E0, N0 = base(3000, 1200)
HERE = os.path.dirname(os.path.abspath(__file__))
# temp folders inside tests\ (both listed in .gitignore); exports never go to the project folder
OUT = os.path.join(HERE, "mcp_export_tmp")
IN = os.path.join(HERE, "mcp_import_tmp")
# P: alias A/B/C -> point ID, SER: alias -> serial; LINES: serials of the test linestrings
P, SER = {}, {}
LINES = []
# windows already open before the run; cleanup() closes any other non-modal window left behind
BASE_FORMS = set(f["id"] for f in S.run_ipy("command_ui", "forms", {}))

# IronPython run inside TBC (needs `prefix` defined before it): walk the project's object containers up to
# 3 levels deep and list every object whose Name starts with `prefix` (upper-cased), with serial and type.
# Used to find an import's FileProperties record by file name.
FIND = r"""
hits = []
def walk(c, d=0):
    for o in c:
        try:
            n = str(getattr(o, 'Name', '') or '')
            if n.upper().startswith(prefix):
                hits.append({'serial': int(o.SerialNumber), 'type': o.GetType().Name, 'name': n})
        except Exception: pass
        if d < 3 and hasattr(o, 'GetEnumerator') and not isinstance(o, str):
            try: walk(o, d + 1)
            except Exception: pass
walk(prj)
result = hits
"""


def named(prefix):
    """Objects in the project whose name starts with `prefix` (case-insensitive), de-duplicated by serial.

    The same object can be reached through more than one container, hence the de-duplication. The walk can
    be slow on a big project, so the bridge timeout is raised to 300 s.
    """
    seen, out = set(), []
    for x in S.call_bridge("execute_python", {"code": "prefix = %r\n" % prefix.upper() + FIND, "transaction": False}, timeout=300)["result"]:
        if x["serial"] not in seen:
            seen.add(x["serial"])
            out.append(x)
    return out


def setup():
    """Recreate empty temp folders, make the test layer, three coded points (A, B, C) and one linestring
    through the same three positions."""
    for d in (OUT, IN):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    S.call_bridge("create_layer", {"name": LAYER})
    made = make_points(LAYER, [(E0, N0, 10), (E0 + 100, N0, 11), (E0 + 100, N0 + 50, 12)], code="MCPX")
    for k, p in zip("ABC", made):
        P[k], SER[k] = p["name"], p["serial"]
    LINES.append(make_line(LAYER, "MCP_EXPORT_LINE", [(E0, N0, 10), (E0 + 100, N0, 11), (E0 + 100, N0 + 50, 12)]))
    print("test area E %.2f N %.2f; points %s; line %s" % (E0, N0, P, LINES))


# ---------------------------------------------------------------- export
# tbc_export action=formats: the exporter list must include the CAD "DXF exporter" and the Custom
# "P,N,E,elev,Code" format. The detail shows how many exporters each category has.
def t_export_formats():
    r = S.t_export({"action": "formats"})
    cats = r["formats"]
    ok = "CAD" in cats and "DXF exporter" in cats["CAD"] and "P,N,E,elev,Code" in cats.get("Custom", [])
    record("Export: list formats", ok, {k: len(v) for k, v in cats.items()})


# tbc_export to CSV (Custom > P,N,E,elev,Code) of points A, B, C: one row per point, first column the point
# ID, last column the code MCPX.
def t_export_csv():
    path = os.path.join(OUT, "mcp_points.csv")
    r = S.t_export({"category": "Custom", "format": "P,N,E,elev,Code", "serials": [SER[k] for k in "ABC"], "path": path})
    rows = open(path, encoding="utf-8-sig").read().strip().splitlines() if r["exported"] else []
    ok = sorted(x.split(",")[0] for x in rows) == sorted(P.values()) and all(x.endswith("MCPX") for x in rows)
    record("Export CSV (P,N,E,elev,Code)", ok, "%d bytes, rows %s" % (r["bytes"], rows[:3]), r)


# tbc_export to DXF (CAD > DXF exporter) of the test linestring: over 500 bytes and contains a POLYLINE.
# The file is reused by t_import_dxf.
def t_export_dxf():
    path = os.path.join(OUT, "MCP_EXPORT_LINES.dxf")
    r = S.t_export({"category": "CAD", "format": "DXF exporter", "serials": LINES, "path": path})
    txt = open(path, errors="replace").read() if r["exported"] else ""
    ok = r["bytes"] > 500 and "POLYLINE" in txt
    record("Export DXF", ok, "%d bytes; POLYLINE present %s" % (r["bytes"], "POLYLINE" in txt), r)


# tbc_export to LandXML (Construction > LandXML exporter) of the line and points: a <LandXML document that
# mentions all three point IDs.
def t_export_landxml():
    path = os.path.join(OUT, "mcp_data.xml")
    r = S.t_export({"category": "Construction", "format": "LandXML exporter", "serials": LINES + [SER[k] for k in "ABC"], "path": path})
    txt = open(path, encoding="utf-8", errors="replace").read() if r["exported"] else ""
    found = [P[k] for k in "ABC" if P[k] in txt]
    record("Export LandXML", "<LandXML" in txt and len(found) == 3, "%d bytes; point IDs %s" % (r["bytes"], found), r)


# ---------------------------------------------------------------- import
def remove_import(file_name, extra_serials=()):
    """Delete the imported DATA only. The import's FileProperties record is LEFT in the project: deleting it with the
    Delete command left a broken imported-file entry, and the next import then failed inside TBC (2026-10-14 error
    report: ImportCommandViewModel UpdateFiles NullReferenceException during RawDataContainer calculate)."""
    if extra_serials:
        S.t_delete_entities({"serials": list(extra_serials)})
        S.wait_idle()
    return [x["serial"] for x in named(file_name) if x["type"] == "FileProperties"]  # reported, not deleted


# tbc_import action=scan on the import folder after writing a two-point CSV (P,E,N,elev,Code; IDs 4790001 and
# 4790002 at N0+300): the scan must list the file (with the importer TBC picked for it).
def t_import_scan():
    with open(os.path.join(IN, "MCP_IMPORT_POINTS.csv"), "w") as f:
        f.write("4790001,%.3f,%.3f,5.000,MCPIMP\n4790002,%.3f,%.3f,5.500,MCPIMP\n" % (E0, N0 + 300, E0 + 10, N0 + 300))
    r = S.t_import({"action": "scan", "folder": IN})
    files = {x["name"]: x["importer"] for x in r["files"]}
    ok = "MCP_IMPORT_POINTS.csv" in files
    record("Import: scan folder", ok, files, r)


# tbc_import action=import (confirm=true) of that CSV: point 4790001 must arrive at (E0, N0+300) with code
# MCPIMP. Refuses to run when the ID already exists (e.g. left over from an earlier run). Needs t_import_scan's
# file. The imported points are deleted afterwards; the import record stays.
def t_import_csv():
    if point("4790001"):
        record("Import CSV", False, "point 4790001 already exists - refusing to import duplicates")
        return
    r = S.t_import({"action": "import", "folder": IN, "files": ["MCP_IMPORT_POINTS.csv"], "confirm": True})
    a, b = point("4790001"), point("4790002")
    ok = bool(a and b) and abs(a["easting"] - E0) < 0.01 and abs(a["northing"] - (N0 + 300)) < 0.01 and a["feature_code"] == "MCPIMP"
    record("Import CSV (P,E,N,elev,Code)", ok, "importer %s; 4790001 -> %s" % (r.get("importers"), a), r)
    recs = remove_import("MCP_IMPORT_POINTS.csv", [p["serial"] for p in (a, b) if p])
    print("      removed the imported points; import record(s) %s left in the project on purpose" % recs)


# tbc_import of the DXF that t_export_dxf wrote (allow_cad=true lets the CAD importer run): no errors and at
# least one new object on the test layer. The imported objects are deleted afterwards; the record stays.
def t_import_dxf():
    src = os.path.join(OUT, "MCP_EXPORT_LINES.dxf")
    if not os.path.exists(src):
        record("Import DXF", False, "needs the DXF from Export DXF")
        return
    shutil.copy(src, os.path.join(IN, "MCP_IMPORT_LINES.dxf"))   # a DXF that TBC wrote itself
    before = set(e["serial"] for e in entities(LAYER))
    r = S.t_import({"action": "import", "folder": IN, "files": ["MCP_IMPORT_LINES.dxf"], "confirm": True, "allow_cad": True})
    new = [e for e in entities(LAYER) if e["serial"] not in before]
    ok = not r.get("errors") and len(new) >= 1
    record("Import DXF (TBC-exported)", ok, "importer %s; new on %s: %s" % (r.get("importers"), LAYER, [e["type"] for e in new]), r)
    recs = remove_import("MCP_IMPORT_LINES.dxf", [e["serial"] for e in new])
    print("      removed %d imported objects; import record(s) %s left on purpose" % (len(new), recs))


# run order matters: export_dxf feeds import_dxf, import_scan writes the CSV that import_csv imports
TESTS = [t_export_formats, t_export_csv, t_export_dxf, t_export_landxml, t_import_scan, t_import_csv, t_import_dxf]


def teardown():
    """Delete the test layer's contents and the layer, close leftover windows, remove both temp folders."""
    cleanup([LAYER], base_forms=BASE_FORMS)
    for d in (OUT, IN):
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    # "--keep" skips the teardown; note it is also passed to run() as a test name, where it matches nothing,
    # so "--keep" alone runs no tests (combine it with test names)
    run(TESTS, sys.argv[1:], setup, lambda: None if "--keep" in sys.argv else teardown())
    json.dump({"results": __import__("tbc_testkit").results}, open("home_results.json", "w"), indent=1)
