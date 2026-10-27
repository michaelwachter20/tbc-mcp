# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Offline tests for the fixes made after the documentation pass (docs/ARCHITECTURE.md, Known issues), without TBC.

Needs TBC
    No. The server's tool handlers are called in-process with the parts that would talk to TBC replaced by small
    stand-ins, and the protocol checks run the real server over stdio against a fake bridge (a local socket
    that answers like the macro, slowly on purpose). Knowledge folders are temporary copies.

How to run
    py -3.12 tests\\test_server_fixes.py

What it checks
    - a valid JSON message that isn't an object gets "Invalid Request" and the server keeps running
    - pings are answered while a slow tool call is still waiting for TBC; tool calls stay in order
    - guard_fill refuses a required field that comes after the field that needs it
    - safe_dismiss closes popups from the highest index down (closing one renumbers the ones after it)
    - ui_grid re-reads a clicked checkbox row by its index, also beyond row 500
    - create_points refuses numbers counted up from start_id that already exist
    - tbc_export checks the path before opening the Export pane, and an untouched file isn't "exported"
    - tbc_memory with command= stores the lesson under the command, so the confirm gate applies to it
    - the live suites' run() ignores --keep when choosing tests, and save_results() writes into tests\\
    - write_tab_skill.py works without a "tab" key; tools\\sdkdoc.py honors TBC_SDK_DOCS and never caches nothing
    - tbc_help no longer imports html.parser

Pass / fail
    PASS/FAIL per check; exit code 0 when all pass, else 1. Nothing outside temporary folders is written.
"""
import ast, json, os, shutil, socket, subprocess, sys, tempfile, threading, time

here = os.path.dirname(os.path.abspath(__file__))
repo = os.path.normpath(os.path.join(here, ".."))
server = os.path.join(repo, "mcp_server", "tbc_mcp_server.py")
work = tempfile.mkdtemp(prefix="tbc_mcp_fixes_")
general = os.path.join(work, "general")
os.makedirs(os.path.join(general, "commands"))
os.environ.update({"TBC_MCP_KNOWLEDGE_DIR": general, "PROJECT_KNOWLEDGE_DIR": os.path.join(work, "shared"),
                   "TBC_MCP_INFO": os.path.join(work, "no_bridge.json"), "TBC_MCP_EXIT_WITH_TBC": "0",
                   "TBC_MCP_USER_DIR": os.path.join(work, "user")})
sys.path.insert(0, os.path.join(repo, "mcp_server"))
sys.path.insert(0, here)
import tbc_mcp_server as S  # noqa: E402

ok = True


def check(cond, label):
    global ok
    ok = ok and bool(cond)
    print(("PASS " if cond else "FAIL ") + label)


def raises(fn, text):
    try:
        fn()
    except Exception as ex:
        return text.lower() in str(ex).lower()
    return False


class patched:
    """Temporarily replace attributes of a module (restored on exit)."""
    def __init__(self, mod, **values):
        self.mod, self.values, self.saved = mod, values, {}

    def __enter__(self):
        for k, v in self.values.items():
            self.saved[k] = getattr(self.mod, k)
            setattr(self.mod, k, v)

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            setattr(self.mod, k, v)


# --- 1. protocol: non-object JSON, pings during a slow call ---------------------------------------------------
class FakeBridge:
    """Answers bridge requests like the macro does; project_info takes `delay` seconds."""
    def __init__(self, delay):
        self.delay, self.token = delay, "fake-token-123456"
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.one, args=(c,), daemon=True).start()

    def one(self, c):
        with c:
            req = json.loads(c.makefile("r", encoding="utf-8").readline())
            if req["method"] == "project_info":
                time.sleep(self.delay)
                result = {"name": "Fake", "path": ""}
            else:
                result = {"result": "", "stdout": ""}
            c.sendall((json.dumps({"id": req["id"], "ok": True, "result": result}) + "\n").encode("utf-8"))


fake = FakeBridge(delay=3.0)
info = os.path.join(work, "bridge.json")
with open(info, "w") as f:
    json.dump({"port": fake.port, "token": fake.token, "pid": os.getpid()}, f)
p = subprocess.Popen([sys.executable, server], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                     env=dict(os.environ, TBC_MCP_INFO=info), text=True, encoding="utf-8")


def send(obj):
    p.stdin.write((obj if isinstance(obj, str) else json.dumps(obj)) + "\n")
    p.stdin.flush()


def read():
    return json.loads(p.stdout.readline())


send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
check(read().get("id") == 1, "server answers initialize")
send("[1, 2]")
r = read()
check(r.get("error", {}).get("code") == -32600, "a JSON array gets 'Invalid Request' (-32600): %s" % r.get("error"))
send({"jsonrpc": "2.0", "id": 2, "method": "ping"})
check(read().get("id") == 2 and p.poll() is None, "...and the server is still running")
t0 = time.time()
send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "project_info", "arguments": {}}})
send({"jsonrpc": "2.0", "id": 4, "method": "ping"})
first = read()
t_first = time.time() - t0
second = read()
t_second = time.time() - t0
check(first.get("id") == 4 and t_first < 2.0, "a ping is answered while a tool call waits for TBC (%.1fs)" % t_first)
check(second.get("id") == 3 and not second["result"]["isError"] and t_second >= 2.5,
      "the slow tool call still completes (%.1fs)" % t_second)
send({"jsonrpc": "2.0", "id": 5, "method": "tools/list"})
send({"jsonrpc": "2.0", "id": 6, "method": "tools/list"})
check([read().get("id"), read().get("id")] == [5, 6], "queued requests are answered in order")
p.stdin.close()
p.wait(timeout=15)

# --- 2. guard_fill: field order ---------------------------------------------------------------------------------
panel = {"command": {"key": "DivideArea"}, "fields": [{"label": "Area to Divide", "value": ""}]}
with patched(S, ui_state=lambda *a, **k: panel):
    check(raises(lambda: S.guard_fill([["Origin", "1"], ["Area to Divide", 5]]), "fill 'area to divide' first"),
          "guard_fill refuses the required field AFTER the trigger field")
    check(S.guard_fill([["Area to Divide", 5], ["Origin", "1"]]) is None, "...and passes it BEFORE")
    panel["fields"][0]["value"] = "Lot 1"
    check(S.guard_fill([["Origin", "1"]]) is None, "...and passes when the panel already has it")

# --- 3. safe_dismiss: highest index first -----------------------------------------------------------------------
used = []
dialogs = [{"index": i, "title": "Popup %d" % i, "buttons": ["Cancel"], "message": ""} for i in range(3)]
with patched(S, run_ipy=lambda m, a, args, **k: used.append(args.get("scope") or args.get("index")) or {},
             dialogs_snapshot=lambda *a, **k: [], native_dialogs=lambda **k: None):
    with patched(S.time, sleep=lambda s: None):
        S.safe_dismiss(dialogs)
check(used == ["dialog:2", "dialog:1", "dialog:0"], "safe_dismiss works from the highest index down: %s" % used)

# --- 4. ui_grid set: re-read the clicked row by its index -------------------------------------------------------
state = {"clicked": False}


def grid_ipy(module, action, args, **k):
    if action == "grid_read":
        n = min(int(args.get("limit") or 200), 1000)
        return {"columns": [{"name": "Chk", "header": "Chk", "type": "CheckBoxColumn"}],
                "rows": [{"_row": i, "Chk": i == 600 and state["clicked"]} for i in range(n)]}
    if action == "grid_click":
        state["clicked"] = True
        return {"row": 600}
    raise AssertionError(action)


with patched(S, run_ipy=grid_ipy, ui_after=lambda *a, **k: {}):
    r = S.t_ui_grid({"action": "set", "row": 600, "column": "Chk", "value": True})
check(r.get("clicked") and r.get("now") is True and "warning" not in r, "ui_grid set finds row 600 after the click: %s" % r)

# --- 5. create_points: start_id clashes -------------------------------------------------------------------------
existing, created = {"5", "6"}, []


def points_bridge(method, params=None, timeout=None):
    if method == "execute_python":
        names = ast.literal_eval(params["code"].split("\n", 1)[0].split("=", 1)[1].strip())
        return {"result": {"max_numeric": 6, "taken": [n for n in names if n in existing]}}
    if method == "create_points":
        created.append([q["name"] for q in params["points"]])
        return {"points": []}
    raise AssertionError(method)


pts = [{"easting": 1, "northing": 1}, {"easting": 2, "northing": 2}, {"easting": 3, "northing": 3}]
with patched(S, call_bridge=points_bridge):
    check(raises(lambda: S.t_create_points({"points": [dict(x) for x in pts], "start_id": 4}), "['5', '6'] already exist")
          and not created, "numbers counted from start_id that already exist are refused before anything is made")
    S.t_create_points({"points": [dict(x) for x in pts], "start_id": 4, "allow_duplicates": True})
    S.t_create_points({"points": [dict(x) for x in pts]})
check(created == [["4", "5", "6"], ["7", "8", "9"]], "allow_duplicates still works; no start_id continues after the highest: %s" % created)

# --- 6. tbc_export: path checked first; an untouched file isn't exported ----------------------------------------
opened = []
with patched(S, t_command_ui_open=lambda a: opened.append(a["key"])):
    check(raises(lambda: S.t_export({"category": "CAD", "format": "DXF", "path": "out.dxf"}), "full file path") and not opened,
          "a relative export path is refused before the Export pane opens")
target = os.path.join(work, "old.csv")
with open(target, "w") as f:
    f.write("old")
os.utime(target, (time.time() - 60, time.time() - 60))
write_it = {"on": False}


def fake_fill(a):
    if write_it["on"]:
        with open(target, "w") as f:
            f.write("new export")
    return {"set": []}


with patched(S, t_command_ui_open=lambda a: opened.append(a["key"]), run_ipy=lambda *a, **k: {"chosen": True},
             ui_state=lambda *a, **k: {"fields": []}, t_command_ui_fill=fake_fill, wait_idle=lambda *a, **k: 0,
             _close_pane=lambda: None, FILL_SETTLE_S=0):
    r = S.t_export({"category": "Custom", "format": "P,N,E", "path": target, "overwrite": True})
    check(r["exported"] is False and "warning" in r, "with overwrite=true an untouched old file is not 'exported'")
    write_it["on"] = True
    r = S.t_export({"category": "Custom", "format": "P,N,E", "path": target, "overwrite": True})
    check(r["exported"] is True and "warning" not in r, "...and a rewritten one is")

# --- 7. tbc_memory: command= puts the lesson under the command --------------------------------------------------
with open(os.path.join(general, "commands", "fakecmd.json"), "w") as f:
    json.dump({"key": "fakecmd", "fields": [], "buttons": [], "notes": []}, f)
rec = S.t_memory({"action": "add", "text": "Fake Command acts immediately, no panel", "topic": "panels", "command": "fakecmd"})
check(rec["topic"] == "fakecmd" and "panels" in rec["tags"], "the lesson's topic is the command, the given topic a tag: %s" % rec)
check(raises(lambda: S.check_known_danger("fakecmd", False), "confirm needed"), "...so the confirm gate now applies to the command")
check("fakecmd" in rec.get("note", ""), "...and the warning names the command")

# --- 8. live-suite helpers: --keep, results file ----------------------------------------------------------------
import tbc_testkit as T  # noqa: E402
ran = []


def t_one():
    ran.append("one")


def t_two():
    ran.append("two")


with patched(S, wait_idle=lambda *a, **k: 0, dialogs_snapshot=lambda *a, **k: []), patched(T, done=lambda: None), \
        patched(T.time, sleep=lambda s: None):
    T.run([t_one, t_two], ["--keep"])
    T.run([t_one, t_two], ["two", "--keep"])
check(ran == ["one", "two", "two"], "run() ignores --keep when choosing tests: %s" % ran)
res_name = "zz_selftest_results.json"
cwd = os.getcwd()
os.chdir(work)
try:
    T.save_results(res_name)
finally:
    os.chdir(cwd)
check(os.path.exists(os.path.join(here, res_name)) and not os.path.exists(os.path.join(work, res_name)),
      "save_results writes into tests\\ whatever the current folder is")
os.remove(os.path.join(here, res_name))

# --- 9. write_tab_skill.py without a "tab" key, sdkdoc.py, tbc_help ---------------------------------------------
fake_repo = os.path.join(work, "repo")
os.makedirs(os.path.join(fake_repo, "tests", "tab_data"))
os.makedirs(os.path.join(fake_repo, "tools"))
shutil.copy(os.path.join(here, "write_tab_skill.py"), os.path.join(fake_repo, "tests"))
shutil.copy(os.path.join(repo, "tools", "sdkdoc.py"), os.path.join(fake_repo, "tools"))
with open(os.path.join(fake_repo, "tests", "tab_data", "demo_tab_survey.json"), "w") as f:
    json.dump({"results": [{"group": "G", "key": "democmd", "caption": "Demo", "outcome": "panel", "fields": ["F"], "buttons": ["OK"]}]}, f)
out = subprocess.run([sys.executable, os.path.join(fake_repo, "tests", "write_tab_skill.py"), "demo", "democat"],
                     capture_output=True, text=True)
skill = os.path.join(fake_repo, "knowledge", "skills", "democat", "demo_tab_overview.skill.md")
check(out.returncode == 0 and os.path.exists(skill) and "DEMO ribbon tab" in open(skill, encoding="utf-8").read(),
      "write_tab_skill.py works on a survey without a 'tab' key")

sdk = os.path.join(work, "sdk")
os.makedirs(sdk)
sdkdoc = os.path.join(fake_repo, "tools", "sdkdoc.py")
cache = os.path.join(fake_repo, "tools", "sdkdoc.pkl")
out = subprocess.run([sys.executable, sdkdoc, "Foo"], capture_output=True, text=True, env=dict(os.environ, TBC_SDK_DOCS=sdk))
check(out.returncode != 0 and "No SDK XML docs" in (out.stderr + out.stdout) and not os.path.exists(cache),
      "sdkdoc.py with no docs says so and caches nothing")
with open(os.path.join(sdk, "Demo.xml"), "w") as f:
    f.write('<doc><assembly><name>DemoAsm</name></assembly><members><member name="T:Foo.Bar"><summary>Hello there</summary>'
            '</member></members></doc>')
out = subprocess.run([sys.executable, sdkdoc, "Foo"], capture_output=True, text=True, env=dict(os.environ, TBC_SDK_DOCS=sdk))
check(out.returncode == 0 and "[DemoAsm] T:Foo.Bar  -- Hello there" in out.stdout and os.path.exists(cache),
      "sdkdoc.py reads TBC_SDK_DOCS and caches what it found")

out = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); import tbc_help; print('html.parser' in sys.modules)"
                      % os.path.join(repo, "mcp_server")], capture_output=True, text=True)
check(out.stdout.strip() == "False", "tbc_help no longer imports html.parser (it crashed CPython 3.15)")

shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if ok else 1)
