# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
End-to-end smoke test: spawn the MCP server over stdio and call tools.
Usage: python test_mcp_stdio.py [info_file]
With an info file from ipy_bridge_harness.py this tests bridge comms outside TBC;
with no argument it uses the real bridge (TBC running + macro started).

Needs TBC
    With no argument: yes (TBC 2026.10, a project open, MCP Bridge on). With an info file argument: no TBC,
    but a bridge stand-in must be listening, e.g. tests\\dev\\ipy_bridge_harness.py run under TBC's
    IronPython (see tests\\dev\\run_ipy.ps1), which writes that info file.

How to run
    py -3.12 tests\\test_mcp_stdio.py
    py -3.12 tests\\test_mcp_stdio.py <path to the harness's info file>

What it does
    Starts the server as an MCP client would (stdio, one JSON-RPC message per line), runs initialize,
    sends notifications/initialized, lists the tools, then calls bridge_status, execute_python (one good
    script, one that raises), search_sdk_docs (needs the Macros SDK docs installed) and, against real TBC
    only, the read-only tools project_info, list_layers, list_points, list_entities and list_surfaces.
    Nothing in the project is changed.

What it writes
    Console only: each tool's ok/error status and the first 1500 characters of its reply.

Pass / fail
    A smoke test read by eye: nothing is asserted. The 'boom' call is expected to come back as an error.
    A crash (e.g. no reply line) raises an exception.
"""
import json, os, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
server = os.path.join(here, "..", "mcp_server", "tbc_mcp_server.py")
env = dict(os.environ)
# point the server at the harness's info file instead of the real bridge's
if len(sys.argv) > 1:
    env["TBC_MCP_INFO"] = sys.argv[1]
p = subprocess.Popen([sys.executable, server], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env,
                     text=True, encoding="utf-8")
# JSON-RPC request id counter
n = 0


def rpc(method, params=None, notify=False):
    """Send one JSON-RPC message to the server and return its parsed reply.

    notify=True sends a notification (no id) and returns None without reading a reply.
    """
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
    """Call one MCP tool (tools/call), print its status and the start of its text reply, return the result."""
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
# execute_python: a script that prints and sets `result` (with a float, None and a string to check JSON
# conversion), then one that raises, which should come back as an error reply
tool("execute_python", {"code": "import sys\nprint('hello from', sys.version)\nresult = {'sum': 1 + 2, 'items': [1.5, None, 'x']}"})
tool("execute_python", {"code": "raise ValueError('boom')"})
tool("search_sdk_docs", {"query": r"Coordinates\.Point\.CreatePoint", "search_summaries": True})
# the project read tools only make sense against a real TBC with a project open
if len(sys.argv) == 1:
    tool("project_info")
    tool("list_layers")
    tool("list_points", {"limit": 5})
    tool("list_entities", {"limit": 10})
    tool("list_surfaces")
# closing stdin ends the server's read loop, so it exits
p.stdin.close()
p.wait(timeout=10)
