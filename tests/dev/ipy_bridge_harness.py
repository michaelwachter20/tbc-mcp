# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Run the bridge's socket core under TBC's ipy.exe *outside* TBC (no project).
Usage: ipy.exe ipy_bridge_harness.py <info_file> [seconds]
Only TBC-independent handlers (ping, execute_python without a project) work here.
"""
import sys, os, time
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "..", "tbc_macro"))
import TbcMcpBridge as B

B.INFO_FILE = sys.argv[1]
secs = int(sys.argv[2]) if len(sys.argv) > 2 else 60
srv = B.BridgeServer(B.TbcHandlers(None), None, port=47900)
print("listening on", srv.start(), "in_tbc =", B.IN_TBC)
sys.stdout.flush()
time.sleep(secs)
srv.stop()
print("stopped")
