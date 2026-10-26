# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Dev runner for mcp_server/ipy/command_ui.py against the live bridge.
Usage: python ui_dev.py <action> '<json args>'     e.g.  python ui_dev.py state '{}'
       python ui_dev.py open <command_key>

One-off development probe for working on the panel engine: runs any action of mcp_server\\ipy\\command_ui.py
(state, fill, click, forms, grid_read, license ...) directly and prints the raw JSON, without the server's
tool layer around it.

Needs TBC
    Yes: TBC 2026.10 with a project open and the MCP Bridge macro on.

How to run
    py -3.12 tests\\dev\\ui_dev.py state "{}"
    py -3.12 tests\\dev\\ui_dev.py open <command_key>     launch a command, wait 2.5 s, print the panel state
    "open" goes straight to the bridge's run_command: no license check, no pacing, no wait for Compute
    Project. Actions such as fill or click change TBC exactly as the tools would.

Output
    The action's result as indented JSON on the console.
"""
import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "mcp_server"))
import tbc_mcp_server as S

# read once per run, so edits to command_ui.py are picked up on the next run without reinstalling the macro
src = open(os.path.join(os.path.dirname(S.__file__), "ipy", "command_ui.py"), encoding="utf-8").read()


def ui(action, args):
    """Run command_ui.py inside TBC with ACTION/ARGS prepended, the same way the server's run_ipy() does
    (here without tolerating a BOM), and return its `result`."""
    code = "ACTION = %r\nimport json as _j\nARGS = _j.loads(%r)\n" % (action, json.dumps(args)) + src
    return S.call_bridge("execute_python", {"code": code, "transaction": False})["result"]


if sys.argv[1] == "open":
    S.call_bridge("run_command", {"key": sys.argv[2]})
    time.sleep(2.5)
    print(json.dumps(ui("state", {}), indent=1))
else:
    print(json.dumps(ui(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}), indent=1))
