# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Tests the MCP server's TBC watchdog without TBC: a dummy process plays the role of TBC.
  1. stale info file (dead pid) -> tool call reports 'TBC is not running' and the file is removed
  2. server exits on its own shortly after the 'TBC' process is killed
Usage: python test_watchdog.py
"""
import json, os, subprocess, sys, tempfile, time

here = os.path.dirname(os.path.abspath(__file__))
server = os.path.join(here, "..", "mcp_server", "tbc_mcp_server.py")
info = os.path.join(tempfile.gettempdir(), "tbc_mcp_watchdog_test.json")
env = dict(os.environ, TBC_MCP_INFO=info)
ok = True


def check(cond, label):
    global ok
    ok = ok and cond
    print(("PASS " if cond else "FAIL ") + label)


def start_server():
    p = subprocess.Popen([sys.executable, server], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env, text=True, encoding="utf-8")
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2025-06-18", "capabilities": {}}}) + "\n")
    p.stdin.flush()
    p.stdout.readline()
    return p


# --- 1. stale info file --------------------------------------------------------
dead = subprocess.Popen([sys.executable, "-c", "pass"])
dead.wait()
with open(info, "w") as f:
    json.dump({"port": 1, "token": "x", "pid": dead.pid}, f)
p = start_server()
p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                          "params": {"name": "bridge_status", "arguments": {}}}) + "\n")
p.stdin.flush()
r = json.loads(p.stdout.readline())["result"]
check(r["isError"] and "not running" in r["content"][0]["text"], "stale file -> 'TBC is not running': %r" % r["content"][0]["text"][:80])
check(not os.path.exists(info), "stale info file removed")
check(p.poll() is None, "server keeps running when TBC was never seen")
p.kill()

# --- 2. watchdog exit -------------------------------------------------------------
fake_tbc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
with open(info, "w") as f:
    json.dump({"port": 1, "token": "x", "pid": fake_tbc.pid}, f)
p = start_server()
time.sleep(5)
check(p.poll() is None, "server running while 'TBC' is alive")
fake_tbc.kill()
t0 = time.time()
while p.poll() is None and time.time() - t0 < 10:
    time.sleep(0.2)
check(p.poll() is not None, "server exited %.1fs after 'TBC' was killed" % (time.time() - t0))
check(not os.path.exists(info), "info file cleaned up after crash")
print("stderr:", p.stderr.read().strip().splitlines()[-1:])
if p.poll() is None:
    p.kill()
sys.exit(0 if ok else 1)
