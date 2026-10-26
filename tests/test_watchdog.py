# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Tests the MCP server's TBC watchdog without TBC: a dummy process plays the role of TBC.
  1. stale info file (dead pid) -> tool call reports 'TBC is not running' and the file is removed
  2. server exits on its own shortly after the 'TBC' process is killed
Usage: python test_watchdog.py

Needs TBC
    No. Offline: a short-lived Python process plays TBC (only its pid matters). Windows only in practice:
    the server's pid_alive() reports every pid as alive on other systems.

How to run
    py -3.12 tests\\test_watchdog.py
    Takes about 10 seconds.

What it creates and cleans up
    A private bridge info file %TEMP%\\tbc_mcp_watchdog_test.json (the server is pointed at it through
    TBC_MCP_INFO, so a real bridge's info file is never touched) and two server processes. The checks expect
    the server to delete the info file itself; the servers are killed at the end if still running.

What it writes
    Console only: one PASS/FAIL line per check and the server's last stderr line.

Pass / fail
    Exit code 0 when every check passed, 1 otherwise.
"""
import json, os, subprocess, sys, tempfile, time

here = os.path.dirname(os.path.abspath(__file__))
server = os.path.join(here, "..", "mcp_server", "tbc_mcp_server.py")
# a test-only info file, so the real %TEMP%\tbc_mcp_bridge.json is never read or deleted
info = os.path.join(tempfile.gettempdir(), "tbc_mcp_watchdog_test.json")
env = dict(os.environ, TBC_MCP_INFO=info)
ok = True


def check(cond, label):
    """Print PASS/FAIL for one check and fold it into the overall result `ok`."""
    global ok
    ok = ok and cond
    print(("PASS " if cond else "FAIL ") + label)


def start_server():
    """Start the MCP server over stdio and complete the MCP initialize handshake (reads one reply line).

    Starting it also starts the server's watchdog thread (TBC_MCP_EXIT_WITH_TBC defaults to on), which
    polls the info file's pid every 2 seconds.
    """
    p = subprocess.Popen([sys.executable, server], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env, text=True, encoding="utf-8")
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2025-06-18", "capabilities": {}}}) + "\n")
    p.stdin.flush()
    p.stdout.readline()
    return p


# --- 1. stale info file --------------------------------------------------------
# An info file left by a TBC that has since died (a pid that has exited): the first tool call must report
# "not running" and delete the file, and the server must stay up (it never saw this TBC alive, so the
# watchdog has nothing to exit for).
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
# A live "TBC" (a process sleeping 60 s): the server must keep running while it lives, then exit by itself
# within 10 s of it being killed, and remove the info file on the way out.
fake_tbc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
with open(info, "w") as f:
    json.dump({"port": 1, "token": "x", "pid": fake_tbc.pid}, f)
p = start_server()
# long enough for the watchdog (2 s poll) to see the fake TBC alive at least once
time.sleep(5)
check(p.poll() is None, "server running while 'TBC' is alive")
fake_tbc.kill()
t0 = time.time()
# wait up to 10 s for the server to exit on its own
while p.poll() is None and time.time() - t0 < 10:
    time.sleep(0.2)
check(p.poll() is not None, "server exited %.1fs after 'TBC' was killed" % (time.time() - t0))
check(not os.path.exists(info), "info file cleaned up after crash")
print("stderr:", p.stderr.read().strip().splitlines()[-1:])
if p.poll() is None:
    p.kill()
sys.exit(0 if ok else 1)
