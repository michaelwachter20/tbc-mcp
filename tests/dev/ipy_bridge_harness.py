# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Run the bridge's socket core under TBC's ipy.exe *outside* TBC (no project).
Usage: ipy.exe ipy_bridge_harness.py <info_file> [seconds]
Only TBC-independent handlers (ping, execute_python without a project) work here.

One-off development probe: a stand-in bridge for testing the MCP server's socket/token protocol without
TBC. Pair it with tests\\test_mcp_stdio.py <info_file>, which points the server at the info file this writes.

Needs TBC
    No running TBC, but TBC's IronPython 3.4 and DLLs from the TBC install (it imports the bridge macro).
    The usage line above names ipy.exe; tests\\dev\\run_ipy.ps1 is the repo's way to run TBC's IronPython:
    powershell -ExecutionPolicy Bypass -File tests\\dev\\run_ipy.ps1 tests\\dev\\ipy_bridge_harness.py <info_file> [seconds]

What it creates and cleans up
    A bridge listening on 127.0.0.1 from port 47900 (or the next free one) for `seconds` (default 60), with
    its port and token in <info_file>; stop() deletes the info file at the end.
"""
import sys, os, time
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "..", "tbc_macro"))
import TbcMcpBridge as B

# write the port/token to the given file, not the real %TEMP%\tbc_mcp_bridge.json
B.INFO_FILE = sys.argv[1]
secs = int(sys.argv[2]) if len(sys.argv) > 2 else 60
# TbcHandlers(None): no TBC behind it; a port away from the real bridge's 47821
srv = B.BridgeServer(B.TbcHandlers(None), None, port=47900)
print("listening on", srv.start(), "in_tbc =", B.IN_TBC)
sys.stdout.flush()
time.sleep(secs)
srv.stop()
print("stopped")
