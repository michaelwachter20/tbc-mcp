# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Live usage tests for the Home tab's Import and Export (the user's scope for this tab), through the MCP tools
tbc_export / tbc_import. Throwaway points/lines on layer MCP_HOMETEST; exported files go to tests\\mcp_export_tmp
(never the project folder) and are checked, then deleted. Never uses Remote Save / Connected Workspace (online).
Import copies each imported file into the project folder: the user chose to leave those copies (names reported).
py -3.12 home_tests.py [names]"""
import json, os, shutil, sys
from tbc_testkit import S, record, base, entities, make_points, make_line, cleanup, run, point

LAYER = "MCP_HOMETEST"
E0, N0 = base(3000, 1200)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "mcp_export_tmp")
IN = os.path.join(HERE, "mcp_import_tmp")
P, SER = {}, {}
LINES = []
BASE_FORMS = set(f["id"] for f in S.run_ipy("command_ui", "forms", {}))

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
    seen, out = set(), []
    for x in S.call_bridge("execute_python", {"code": "prefix = %r\n" % prefix.upper() + FIND, "transaction": False}, timeout=300)["result"]:
        if x["serial"] not in seen:
            seen.add(x["serial"])
            out.append(x)
    return out


def setup():
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
def t_export_formats():
    r = S.t_export({"action": "formats"})
    cats = r["formats"]
    ok = "CAD" in cats and "DXF exporter" in cats["CAD"] and "P,N,E,elev,Code" in cats.get("Custom", [])
    record("Export: list formats", ok, {k: len(v) for k, v in cats.items()})


def t_export_csv():
    path = os.path.join(OUT, "mcp_points.csv")
    r = S.t_export({"category": "Custom", "format": "P,N,E,elev,Code", "serials": [SER[k] for k in "ABC"], "path": path})
    rows = open(path, encoding="utf-8-sig").read().strip().splitlines() if r["exported"] else []
    ok = sorted(x.split(",")[0] for x in rows) == sorted(P.values()) and all(x.endswith("MCPX") for x in rows)
    record("Export CSV (P,N,E,elev,Code)", ok, "%d bytes, rows %s" % (r["bytes"], rows[:3]), r)


def t_export_dxf():
    path = os.path.join(OUT, "MCP_EXPORT_LINES.dxf")
    r = S.t_export({"category": "CAD", "format": "DXF exporter", "serials": LINES, "path": path})
    txt = open(path, errors="replace").read() if r["exported"] else ""
    ok = r["bytes"] > 500 and "POLYLINE" in txt
    record("Export DXF", ok, "%d bytes; POLYLINE present %s" % (r["bytes"], "POLYLINE" in txt), r)


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


def t_import_scan():
    with open(os.path.join(IN, "MCP_IMPORT_POINTS.csv"), "w") as f:
        f.write("4790001,%.3f,%.3f,5.000,MCPIMP\n4790002,%.3f,%.3f,5.500,MCPIMP\n" % (E0, N0 + 300, E0 + 10, N0 + 300))
    r = S.t_import({"action": "scan", "folder": IN})
    files = {x["name"]: x["importer"] for x in r["files"]}
    ok = "MCP_IMPORT_POINTS.csv" in files
    record("Import: scan folder", ok, files, r)


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


TESTS = [t_export_formats, t_export_csv, t_export_dxf, t_export_landxml, t_import_scan, t_import_csv, t_import_dxf]


def teardown():
    cleanup([LAYER], base_forms=BASE_FORMS)
    for d in (OUT, IN):
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    run(TESTS, sys.argv[1:], setup, lambda: None if "--keep" in sys.argv else teardown())
    json.dump({"results": __import__("tbc_testkit").results}, open("home_results.json", "w"), indent=1)
