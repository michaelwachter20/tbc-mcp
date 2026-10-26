# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""One-off development probe: does the bridge's "is it really running?" check notice a dead listener?

Probes BridgeServer.is_alive() and _bridge_actually_running() in tbc_macro\\TbcMcpBridge.py, the checks behind
the ribbon light ("green really means connected", README). Starts a bridge server outside TBC, stores it in
the AppDomain slot the macro uses (INSTANCE_KEY), then stops only its TCP listener to simulate it dying.

Needs TBC
    No running TBC, but TBC's IronPython 3.4 and DLLs from the TBC install (it imports the bridge macro).

How to run
    powershell -ExecutionPolicy Bypass -File tests\\dev\\run_ipy.ps1 tests\\dev\\ipy_alive_check.py

What it creates and cleans up
    A bridge listening on 127.0.0.1 port 47910 (or the next free one) with its own info file
    %TEMP%\\tbc_mcp_alive_test.json instead of the real one; stopped and the AppDomain slot cleared at the end.

Output / pass
    Three console lines, read by eye: expected True/True while running, False/False after the listener died,
    and False once the slot is cleared.
"""
import sys, os, tempfile
# sys.argv[0] (set by run_ipy.ps1 to the script path) locates the macro folder
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "..", "..", "tbc_macro"))
import TbcMcpBridge as B
from System import AppDomain
# never touch the real bridge's info file
B.INFO_FILE = os.path.join(tempfile.gettempdir(), "tbc_mcp_alive_test.json")
# TbcHandlers(None): no TBC project/UI behind it; a port away from the real bridge's 47821
srv = B.BridgeServer(B.TbcHandlers(None), None, port=47910)
srv.start()
AppDomain.CurrentDomain.SetData(B.INSTANCE_KEY, srv)
print("running  -> is_alive:", srv.is_alive(), "| actually_running:", B._bridge_actually_running())
srv.listener.Stop()   # simulate the listener dying underneath us
import time; time.sleep(0.5)
print("listener died -> is_alive:", srv.is_alive(), "| actually_running:", B._bridge_actually_running())
srv.stop()
AppDomain.CurrentDomain.SetData(B.INSTANCE_KEY, None)
print("cleared  -> actually_running:", B._bridge_actually_running())
