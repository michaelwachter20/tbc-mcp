# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
End-to-end smoke test: spawn the MCP server over stdio and call tools.
Usage: python test_mcp_stdio.py [info_file]
With an info file from ipy_bridge_harness.py this tests bridge comms outside TBC;
with no argument it uses the real bridge (TBC running + macro started).
"""
import json, os, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
server = os.path.join(here, "..", "mcp_server", "tbc_mcp_server.py")
env = dict(os.environ)
if len(sys.argv) > 1:
    env["TBC_MCP_INFO"] = sys.argv[1]
p = subprocess.Popen([sys.executable, server], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env,
                     text=True, encoding="utf-8")
n = 0


def rpc(method, params=None, notify=False):
    global n
    msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if not notify:
        n += 1
        msg["id"] = n
    p.stdin.write(json.dumps(msg) + "\n")
    p.stdin.flush()
    if notify:
        return None
    return json.loads(p.stdout.readline())


def tool(name, args=None):
    r = rpc("tools/call", {"name": name, "arguments": args or {}})["result"]
    print("---", name, "error" if r["isError"] else "ok")
    print(r["content"][0]["text"][:1500])
    return r


init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}})
print("initialize:", init["result"]["serverInfo"], init["result"]["protocolVersion"])
rpc("notifications/initialized", notify=True)
tools = rpc("tools/list")["result"]["tools"]
print("tools:", ", ".join(t["name"] for t in tools))

tool("bridge_status")
tool("execute_python", {"code": "import sys\nprint('hello from', sys.version)\nresult = {'sum': 1 + 2, 'items': [1.5, None, 'x']}"})
tool("execute_python", {"code": "raise ValueError('boom')"})
tool("search_sdk_docs", {"query": r"Coordinates\.Point\.CreatePoint", "search_summaries": True})
if len(sys.argv) == 1:
    tool("project_info")
    tool("list_layers")
    tool("list_points", {"limit": 5})
    tool("list_entities", {"limit": 10})
    tool("list_surfaces")
p.stdin.close()
p.wait(timeout=10)
