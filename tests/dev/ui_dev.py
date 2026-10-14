# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Dev runner for mcp_server/ipy/command_ui.py against the live bridge.
Usage: python ui_dev.py <action> '<json args>'     e.g.  python ui_dev.py state '{}'
       python ui_dev.py open <command_key>"""
import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "mcp_server"))
import tbc_mcp_server as S

src = open(os.path.join(os.path.dirname(S.__file__), "ipy", "command_ui.py"), encoding="utf-8").read()


def ui(action, args):
    code = "ACTION = %r\nimport json as _j\nARGS = _j.loads(%r)\n" % (action, json.dumps(args)) + src
    return S.call_bridge("execute_python", {"code": code, "transaction": False})["result"]


if sys.argv[1] == "open":
    S.call_bridge("run_command", {"key": sys.argv[2]})
    time.sleep(2.5)
    print(json.dumps(ui("state", {}), indent=1))
else:
    print(json.dumps(ui(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}), indent=1))
