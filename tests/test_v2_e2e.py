# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Live end-to-end test of the v0.2 tools over MCP stdio (TBC running + bridge ON).
Creates and removes a test point named MCPE2E*, saves two example scripts into knowledge/scripts,
adds then deletes a test lesson. Usage: python test_v2_e2e.py
"""
import json, os, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
server = os.path.join(here, "..", "mcp_server", "tbc_mcp_server.py")
p = subprocess.Popen([sys.executable, server], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
n = [0]
fails = []


def rpc(method, params):
    n[0] += 1
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n[0], "method": method, "params": params}) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())


def tool(name, args=None, expect_error=False, show=600):
    r = rpc("tools/call", {"name": name, "arguments": args or {}})["result"]
    text = r["content"][0]["text"]
    ok = r["isError"] == expect_error
    if not ok:
        fails.append(name)
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, json.dumps(args)[:120] if args else ""))
    print("    " + text[:show].replace("\n", "\n    "))
    try:
        return json.loads(text)
    except ValueError:
        return text


rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
names = [t["name"] for t in rpc("tools/list", {})["result"]["tools"]]
print("tools (%d): %s" % (len(names), ", ".join(names)))

# --- knowledge -------------------------------------------------------------------
tool("tbc_skills", {"action": "list"}, show=300)
tool("tbc_skills", {"action": "search", "query": "create point feature code"}, show=400)
tool("tbc_skills", {"action": "read", "name": "create_point_via_panel"}, show=200)

tool("tbc_script", {"action": "save", "name": "points_in_box", "overwrite": True, "mode": "read",
                    "description": "List points inside an easting/northing box (display units), optionally by layer.",
                    "parameters": [
                        {"name": "min_e", "type": "number", "required": True}, {"name": "min_n", "type": "number", "required": True},
                        {"name": "max_e", "type": "number", "required": True}, {"name": "max_n", "type": "number", "required": True},
                        {"name": "layer", "type": "string", "default": None, "description": "exact layer name"},
                        {"name": "limit", "type": "integer", "default": 200}],
                    "code": (
                        "f = bridge.factor(prj)\n"
                        "out = []\n"
                        "total = 0\n"
                        "for pt in TbcPoint.GetAllPoints(prj):\n"
                        "    pos = pt.Position\n"
                        "    e, n = pos.X * f, pos.Y * f\n"
                        "    if not (args['min_e'] <= e <= args['max_e'] and args['min_n'] <= n <= args['max_n']):\n"
                        "        continue\n"
                        "    lay = bridge.layer_name(prj, pt.Layer)\n"
                        "    if args['layer'] and lay != args['layer']:\n"
                        "        continue\n"
                        "    total += 1\n"
                        "    if len(out) < args['limit']:\n"
                        "        out.append({'name': str(pt.Name), 'e': e, 'n': n, 'z': pos.Z * f, 'layer': lay})\n"
                        "result = {'total': total, 'points': out}\n")})
tool("tbc_script", {"action": "save", "name": "relayer_points_by_code", "overwrite": True, "mode": "write",
                    "description": "Move points whose feature code starts with a prefix onto a layer. dry_run by default.",
                    "parameters": [
                        {"name": "code_prefix", "type": "string", "required": True},
                        {"name": "layer", "type": "string", "required": True},
                        {"name": "dry_run", "type": "boolean", "default": True}],
                    "code": (
                        "pref = args['code_prefix'].upper()\n"
                        "dry = args['dry_run']\n"
                        "hits = []\n"
                        "for pt in TbcPoint.GetAllPoints(prj):\n"
                        "    try:\n"
                        "        code = str(pt.FeatureCode or '')\n"
                        "        if code.upper().startswith(pref):\n"
                        "            hits.append(str(pt.Name))\n"
                        "            if not dry:\n"
                        "                pt.Layer = Layer.FindOrCreateLayer(prj, args['layer']).SerialNumber\n"
                        "    except Exception as ex:\n"
                        "        print('skipped %s: %s' % (pt.Name, ex))\n"
                        "print('%s %d points' % ('would move' if dry else 'moved', len(hits)))\n"
                        "result = {'count': len(hits), 'sample': hits[:15], 'dry_run': dry}\n")})
tool("tbc_script", {"action": "save", "name": "broken", "mode": "read", "code": "def oops(:\n  pass"}, expect_error=True, show=200)
tool("tbc_script", {"action": "list"}, show=400)
tool("tbc_script", {"action": "run", "name": "points_in_box",
                    "args": {"min_e": 969300, "min_n": 827000, "max_e": 969400, "max_n": 827100, "limit": 3}})
tool("tbc_script", {"action": "run", "name": "relayer_points_by_code", "args": {"code_prefix": "SAND", "layer": "X"}})
tool("tbc_script", {"action": "run", "name": "points_in_box", "args": {"min_e": 1}}, expect_error=True, show=200)

les = tool("tbc_memory", {"action": "add", "topic": "addpoint", "text": "E2E TEST LESSON - delete me", "tags": ["test"]})
tool("tbc_memory", {"action": "search", "query": "E2E TEST LESSON"}, show=300)

# --- command panel automation ----------------------------------------------------------
st = tool("command_ui_open", {"key": "addpoint"}, show=300)
print("    remembered:", st.get("remembered") if isinstance(st, dict) else None)
f = tool("command_ui_fill", {"values": {"Point ID": "MCPE2E1", "Feature code": "E2E", "Northing": "10540",
                                        "Easting": "20540", "Elevation": "7"}, "press": "Add"}, show=900)
dup = tool("command_ui_fill", {"values": [["Point ID", "MCPE2E1"], ["Northing", "10550"], ["Easting", "20550"]],
                               "press": "Add"}, show=900)
if isinstance(dup, dict) and dup.get("after", {}).get("dialogs"):
    tool("tbc_dialogs", {"action": "list"}, show=400)
    tool("tbc_dialogs", {"action": "click", "button": "No"}, show=300)
else:
    fails.append("expected duplicate popup")
tool("command_ui_inspect", {"include_text": False}, show=200)
tool("command_ui_close")
pts = tool("list_points", {"name_contains": "MCPE2E"}, show=500)
if not (isinstance(pts, dict) and pts["total_matched"] == 1 and pts["points"][0]["feature_code"] == "E2E"):
    fails.append("point verification")
tool("delete_entities", {"serials": [q["serial"] for q in pts.get("points", [])]})
if isinstance(les, dict):
    tool("tbc_memory", {"action": "delete", "id": les["id"]})

print("\nRESULT:", "ALL PASS" if not fails else "FAILURES: %s" % fails)
p.stdin.close()
p.wait(timeout=10)
