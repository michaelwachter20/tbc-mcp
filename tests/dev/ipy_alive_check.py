# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "..", "..", "tbc_macro"))
import TbcMcpBridge as B
from System import AppDomain
B.INFO_FILE = os.path.join(tempfile.gettempdir(), "tbc_mcp_alive_test.json")
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
