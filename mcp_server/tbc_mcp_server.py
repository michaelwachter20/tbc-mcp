# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Trimble Business Center MCP server (stdio, no third-party dependencies).

Forwards MCP tool calls to the TbcMcpBridge macro running inside TBC and
offers an offline search over the TBC SDK XML documentation.

Environment variables (all optional):
  TBC_MCP_INFO      path of the bridge info file (default %TEMP%\\tbc_mcp_bridge.json)
  TBC_MCP_PORT      override port      (with TBC_MCP_TOKEN)
  TBC_MCP_TOKEN     override token
  TBC_MCP_TIMEOUT   seconds to wait for TBC to answer (default 120)
  TBC_SDK_DOCS      folder with the SDK *.xml docs (default C:\\Program Files (x86)\\Trimble\\Macros SDK)
  TBC_MCP_ALLOW_PYTHON  set to 0 to hide the execute_python tool
  TBC_MCP_EXIT_WITH_TBC set to 0 to keep running after TBC closes (default: exit when TBC exits/crashes)
  CIVIL3D_KNOWLEDGE_DIR shared project knowledge base (default Documents\\Civil3DMcp-KnowledgeBase, as Civil 3D MCP)
"""
import glob
import itertools
import json
import os
import re
import socket
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import knowledge as K  # noqa: E402
import projects as P  # noqa: E402
import tbc_help as HELP  # noqa: E402

IPY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ipy")

SERVER_NAME = "tbc-mcp"
SERVER_VERSION = "0.3.0"
SUPPORTED_PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]

INFO_FILE = os.environ.get("TBC_MCP_INFO") or os.path.join(tempfile.gettempdir(), "tbc_mcp_bridge.json")
TIMEOUT = float(os.environ.get("TBC_MCP_TIMEOUT", "120"))
SDK_DOCS = os.environ.get("TBC_SDK_DOCS") or r"C:\Program Files (x86)\Trimble\Macros SDK"
ALLOW_PYTHON = os.environ.get("TBC_MCP_ALLOW_PYTHON", "1") != "0"
EXIT_WITH_TBC = os.environ.get("TBC_MCP_EXIT_WITH_TBC", "1") != "0"


def log(*a):
    print("[tbc-mcp]", *a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Bridge client
# ---------------------------------------------------------------------------
class BridgeError(Exception):
    pass


_ids = itertools.count(1)


def pid_alive(pid):
    """True if a process with this pid is running (Windows; falls back to True elsewhere)."""
    if not pid:
        return False
    if os.name != "nt":
        return True
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ctypes.GetLastError() == 5  # access denied => exists
    try:
        code = ctypes.c_ulong()
        return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def read_info():
    try:
        with open(INFO_FILE, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


def bridge_endpoint():
    port, token = os.environ.get("TBC_MCP_PORT"), os.environ.get("TBC_MCP_TOKEN")
    if port and token:
        return int(port), token
    try:
        with open(INFO_FILE, "r", encoding="utf-8-sig") as f:
            info = json.load(f)
        if info.get("pid") and not pid_alive(info["pid"]):
            # TBC crashed and left the file behind
            try:
                os.remove(INFO_FILE)
            except OSError:
                pass
            raise BridgeError("TBC is not running (it closed or crashed). Start TBC, open a project and click "
                              "Macros > MCP > 'MCP Bridge'.")
        return int(info["port"]), info["token"]
    except BridgeError:
        raise
    except FileNotFoundError:
        raise BridgeError(
            "TBC bridge is not running. In Trimble Business Center open a project and click "
            "Macros > MCP > 'MCP Bridge' to start it (info file not found: %s)." % INFO_FILE)
    except Exception as ex:
        raise BridgeError("Could not read bridge info file %s: %s" % (INFO_FILE, ex))


def call_bridge(method, params=None, timeout=None):
    port, token = bridge_endpoint()
    req = {"id": next(_ids), "token": token, "method": method, "params": params or {}}
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.settimeout(timeout or TIMEOUT)
            s.sendall((json.dumps(req) + "\n").encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
    except ConnectionRefusedError:
        raise BridgeError("TBC bridge not reachable on port %d. Is TBC open and the MCP Bridge macro started? "
                          "(It stops when TBC closes.)" % port)
    except socket.timeout:
        raise BridgeError("Timed out waiting for TBC (it may be busy or showing a dialog).")
    if not buf:
        raise BridgeError("Bridge closed the connection without answering.")
    resp = json.loads(buf.decode("utf-8-sig"))
    if not resp.get("ok"):
        msg = resp.get("error", "unknown error")
        if resp.get("traceback"):
            msg += "\n\nTraceback (inside TBC):\n" + resp["traceback"]
        raise BridgeError(msg)
    return resp.get("result")


def run_ipy(module, action, args, transaction=False):
    """Run one of the IronPython helper modules in mcp_server/ipy inside TBC.
    Loaded fresh on every call, so editing them needs no macro reinstall."""
    with open(os.path.join(IPY_DIR, module + ".py"), "r", encoding="utf-8-sig") as f:  # tolerate a BOM
        src = f.read()
    code = "ACTION = %r\nimport json as _j\nARGS = _j.loads(%r)\n" % (action, json.dumps(args or {})) + src
    return call_bridge("execute_python", {"code": code, "transaction": transaction}).get("result")


# ---------------------------------------------------------------------------
# Command panel automation
# ---------------------------------------------------------------------------
SAFE_BUTTONS = ("cancel", "close", "no", "abort")
LICENSE_WORDS = ("licens", "subscription", "entitlement", "not authorized", "unauthorized")


def is_license_dialog(d):
    t = ("%s %s" % (d.get("title") or "", d.get("message") or "")).lower()
    return any(w in t for w in LICENSE_WORDS)


def check_license(key):
    """Silent license check; raises BridgeError instead of letting TBC open its license popups."""
    r = run_ipy("command_ui", "license", {"keys": [key]}).get(key, {})
    if r.get("exists") is False:
        raise BridgeError("No TBC command with key '%s' (see list_commands)." % key)
    if r.get("licensed") is False:
        raise BridgeError("NOT LICENSED: '%s' needs one of %s, which this TBC license doesn't include. "
                          "Skipped without opening it." % (key, r.get("needs_any_of")))
    return r


BUSY_WORDS = ("comput", "processing", "progress", "please wait", "loading", "calculating", "recalculat")
ERROR_LOG = os.path.join(K.ROOT, "memory", "tbc_errors.log")


def is_busy_dialog(d):
    """TBC progress windows (e.g. 'Compute Project' / 'Computing the project' with only a Cancel button).
    These must never be dismissed - pressing Cancel aborts the computation."""
    t = ("%s %s" % (d.get("title") or "", d.get("message") or "")).lower()
    btns = [b.lower() for b in d.get("buttons") or [] if b]
    return any(w in t for w in BUSY_WORDS) and (not btns or btns == ["cancel"])


def is_error_dialog(d):
    t = ("%s %s" % (d.get("title") or "", d.get("message") or "")).lower()
    btns = [b.lower() for b in d.get("buttons") or [] if b]
    return ("<<" in btns or ">>" in btns or "exception" in t or "unexpected error" in t or "has stopped" in t
            or "object reference not set" in t or (d.get("title") or "").strip().lower() == "error")


def log_tbc_error(d, context=""):
    os.makedirs(os.path.dirname(ERROR_LOG), exist_ok=True)
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write("%s  [%s] %s\n%s\n\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), context, d.get("title"), d.get("message")))


def tbc_busy():
    """True while TBC is computing (project calculate loop or a progress window is up)."""
    try:
        st = ui_state(include_text=False)
        if any(is_busy_dialog(x) for x in dialogs_snapshot(st)):
            return True
        return bool(call_bridge("execute_python", {"code": "result = bool(prj.InCalculateLoop) if prj is not None else False",
                                                   "transaction": False}, timeout=60).get("result"))
    except BridgeError as ex:
        if "Timed out" in str(ex):
            return True  # UI thread busy
        raise


def wait_idle(timeout=None, settle=1.5):
    """Block until TBC has finished computing (user preference: wait for Compute Project before anything else)."""
    timeout = float(timeout or os.environ.get("TBC_MCP_IDLE_TIMEOUT", "900"))
    t0 = time.time()
    idle_since = None
    waited = False
    while time.time() - t0 < timeout:
        if tbc_busy():
            waited = True
            idle_since = None
            time.sleep(1.0)
            continue
        if idle_since is None:
            idle_since = time.time()
        if time.time() - idle_since >= (settle if waited else 0):
            return round(time.time() - t0, 1)
        time.sleep(0.5)
    raise BridgeError("TBC is still computing after %d s; waiting longer is up to the user." % timeout)


def safe_dismiss(dialogs=None):
    """Dismiss popups WITHOUT ever pressing an unknown button: only Cancel/Close/No/Abort, otherwise close the
    window like its X button. License popups are always closed with X. Progress windows are never touched
    (we wait for them instead). Error reports are logged before closing. Single pass, never loops."""
    if dialogs is None:
        wait_idle()
        dialogs = dialogs_snapshot()
    actions = []
    for d in dialogs:
        if is_busy_dialog(d):
            actions.append({"dialog": d.get("title"), "action": "left alone (TBC is computing)"})
            continue
        if is_error_dialog(d):
            log_tbc_error(d, "safe_dismiss")
            actions.append({"dialog": d.get("title"), "action": "TBC ERROR logged to %s" % ERROR_LOG, "error": d.get("message")})
        lic = is_license_dialog(d)
        safe = [b for b in d.get("buttons") or [] if b and b.strip().lower() in SAFE_BUTTONS]
        try:
            if safe and not lic:
                if d.get("native"):
                    native_dialogs(click=safe[0])
                else:
                    run_ipy("command_ui", "click", {"button": safe[0], "scope": "dialog:%d" % d["index"]})
                actions.append({"dialog": d.get("title"), "action": "pressed " + safe[0], "license": lic})
            else:
                if d.get("native"):
                    native_dialogs(close_hwnd=d["hwnd"])
                else:
                    run_ipy("command_ui", "close_dialog", {"index": d["index"]})
                actions.append({"dialog": d.get("title"), "action": "closed with X", "license": lic})
        except BridgeError as ex:
            actions.append({"dialog": d.get("title"), "action": "failed: %s" % ex})
    if actions:
        time.sleep(1.0)
        left = [x for x in dialogs_snapshot() if not is_busy_dialog(x)]
        if left:
            actions.append({"still_open": [x.get("title") for x in left],
                            "note": "Stopped after one pass; ask the user to close these."})
    return actions


COMMAND_GAP = float(os.environ.get("TBC_MCP_COMMAND_GAP", "2.5"))
_last_command = [0.0]


def pace_command():
    """TBC is slow to open commands: keep a minimum gap between command launches (user preference)."""
    wait = _last_command[0] + COMMAND_GAP - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_command[0] = time.time()


DANGER_WORDS = ("acts immediately", "opens a trimble web page", "opens the gnss loop closure report", "crashed tbc")


def check_known_danger(key, confirm):
    """Refuse commands the knowledge base marks as acting immediately / opening the browser, unless confirmed."""
    hits = [l["text"] for l in K.list_lessons(key.lower()) if any(w in l["text"].lower() for w in DANGER_WORDS)]
    if hits and not confirm:
        raise BridgeError("CONFIRM NEEDED: '%s' is recorded as: %s  Ask the user, then call again with confirm=true."
                          % (key, " / ".join(hits)))


def t_run_command(a):
    check_license(a["key"])
    check_known_danger(a["key"], a.get("confirm"))
    wait_idle()
    pace_command()
    return call_bridge("run_command", {"key": a["key"], "args": a.get("args") or []})


def t_list_commands(a):
    r = call_bridge("list_commands", a)
    lic = run_ipy("command_ui", "license", {"keys": [c["key"] for c in r.get("commands", [])]})
    for c in r.get("commands", []):
        l = lic.get(c["key"], {})
        c["licensed"] = l.get("licensed")
    return r


def native_dialogs(click=None, close_hwnd=None, set_file=None):
    """Standard Windows dialogs (#32770, e.g. MessageBox / file pickers) owned by TBC. Optionally click a button
    or close one (WM_CLOSE, like its X)."""
    if os.name != "nt":
        return []
    info = read_info() or {}
    pid = info.get("pid")
    if not pid:
        return []
    import ctypes
    import ctypes.wintypes as W
    u = ctypes.windll.user32

    def txt(h):
        n = u.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, b, n + 1)
        return b.value

    def cls(h):
        b = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(h, b, 256)
        return b.value

    out = []
    proto = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

    def top(h, _):
        p = W.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h) and cls(h) == "#32770":
            statics, buttons = [], []

            def kid(k, _2):
                c = cls(k)
                t = txt(k)
                if c == "Button" and t:
                    buttons.append((k, t.replace("&", "")))
                elif c == "Static" and t:
                    statics.append(t)
                return True
            u.EnumChildWindows(h, proto(kid), 0)
            out.append({"native": True, "hwnd": int(h), "title": txt(h), "message": "\n".join(statics)[:1500],
                        "buttons": [b[1] for b in buttons], "_buttons": buttons})
        return True
    u.EnumWindows(proto(top), 0)
    if set_file:
        # standard Open/Save dialog: type the path into the 'File name' edit box (inside a ComboBoxEx32/ComboBox)
        # and press the Open/Save button, like the user
        for d in out:
            edits = []

            def kid2(k, _3):
                if cls(k) == "Edit" and u.IsWindowVisible(k):
                    par = u.GetParent(k)
                    if cls(par) in ("ComboBox", "ComboBoxEx32") or cls(u.GetParent(par)) == "ComboBoxEx32":
                        edits.append(k)
                return True
            u.EnumChildWindows(d["hwnd"], proto(kid2), 0)
            if not edits:
                continue
            u.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, ctypes.c_wchar_p]
            u.SendMessageW(edits[0], 0x000C, 0, set_file)  # WM_SETTEXT
            for hb, t in d["_buttons"]:
                if t.lower() in ("open", "save", "&open", "&save"):
                    u.PostMessageW(hb, 0x00F5, 0, 0)  # BM_CLICK
                    return {"file_set": set_file, "pressed": t, "dialog": d["title"]}
            raise BridgeError("File dialog '%s' has no Open/Save button: %s" % (d["title"], d["buttons"]))
        raise BridgeError("No standard file dialog is open")
    if close_hwnd:
        u.PostMessageW(close_hwnd, 0x0010, 0, 0)  # WM_CLOSE
        return {"closed": close_hwnd}
    if click:
        for d in out:
            for hb, t in d["_buttons"]:
                if t.lower() == click.lower():
                    u.PostMessageW(hb, 0x00F5, 0, 0)  # BM_CLICK
                    return {"clicked": t, "dialog": d["title"]}
        raise BridgeError("No native dialog button '%s'. Open: %s" % (click, [(d["title"], d["buttons"]) for d in out]))
    for d in out:
        d.pop("_buttons")
    return out


def ui_state(scope=None, include_hidden=False, include_text=True):
    return run_ipy("command_ui", "state", {"scope": scope, "include_hidden": include_hidden, "include_text": include_text})


def dialogs_snapshot(st=None):
    st = st or ui_state(include_text=False)
    out = []
    for d in st.get("modal_dialogs", []):
        try:
            ds = ui_state("dialog:%d" % d["index"])
            msg = " ".join([str(f.get("value")) for f in ds.get("fields", []) if f.get("kind") == "text"] + ds.get("texts", []))
            out.append({"index": d["index"], "title": d["title"], "message": msg[:1500],
                        "fields": [f for f in ds.get("fields", []) if f.get("id") != "MessageRichTextBox"],
                        # icon-only buttons have no text: list them by id so they can still be named, never as None
                        "buttons": [b.get("text") or b.get("id") or "" for b in ds.get("buttons", [])
                                    if b.get("text") or b.get("id")]})
        except BridgeError:
            out.append(d)
    out.extend(native_dialogs())
    return out


def ui_after(wait):
    """What happened after pressing a button: open command, popups, field status messages."""
    time.sleep(wait)
    waited = wait_idle()  # TBC may now recompute the project: never act while it does
    st = ui_state(include_text=False)
    snap = {"open_command": st.get("open_command")}
    if waited:
        snap["waited_for_compute_s"] = waited
    d = dialogs_snapshot(st)
    errs = [x for x in d if is_error_dialog(x)]
    if errs:
        for x in errs:
            log_tbc_error(x, "after button press")
        snap["tbc_error"] = [{"title": x.get("title"), "message": x.get("message")} for x in errs]
        snap["hint"] = "TBC reported an error (logged). Stop and tell the user before doing anything else."
        return snap
    lic = [x for x in d if is_license_dialog(x)]
    if lic:
        snap["license_problem"] = [{"title": x.get("title"), "message": x.get("message")} for x in lic]
        snap["auto_dismissed"] = safe_dismiss(lic)
        d = [x for x in d if not is_license_dialog(x)]
    if d:
        snap["dialogs"] = d
        snap["hint"] = "A popup is waiting. Read it and answer with tbc_dialogs action=click (or action=dismiss)."
    stat = [{"field": f.get("label") or f.get("id"), "status": f["status"]} for f in st.get("fields", []) if f.get("status")]
    if stat:
        snap["field_status"] = stat
    return snap


def t_command_ui_open(a):
    key = a["key"]
    check_license(key)
    check_known_danger(key, a.get("confirm"))
    wait_idle()
    pre = dialogs_snapshot()
    if pre:
        raise BridgeError("Popups are already open in TBC; deal with them first (tbc_dialogs): %s"
                          % [(x.get("title"), x.get("buttons")) for x in pre])
    before = ui_state(include_text=False).get("open_command")
    pace_command()
    call_bridge("run_command", {"key": key})
    deadline = time.time() + float(a.get("wait_seconds", 15))
    st = None
    while time.time() < deadline:
        time.sleep(1.0)  # gentle polling: don't keep interrupting TBC while it builds the panel
        st = ui_state(include_text=False)
        oc = st.get("open_command")
        if st.get("modal_dialogs") or (oc and (oc.lower() == key.lower() or oc != before)):
            break
    # TBC builds panels gradually: wait until the field list stops changing before anyone fills it
    sig, stable_since = None, time.time()
    while time.time() < deadline:
        cur = ui_state(include_text=False)
        s = json.dumps([(f.get("id"), f.get("value")) for f in cur.get("fields", [])], default=str)
        if s != sig:
            sig, stable_since = s, time.time()
        elif time.time() - stable_since >= float(a.get("settle_seconds", 1.2)):
            break
        if cur.get("modal_dialogs"):
            break
        time.sleep(0.8)
    st = ui_state(include_hidden=bool(a.get("include_hidden")))
    ds = dialogs_snapshot(st)
    lic = [x for x in ds if is_license_dialog(x)]
    if lic:
        # licensed by feature code but TBC still refused: back out, never click into the license manager
        st = {"not_licensed": True, "command": None, "license_problem": [{"title": x.get("title"), "message": x.get("message")} for x in lic],
              "auto_dismissed": safe_dismiss(lic)}
        try:
            run_ipy("command_ui", "close", {"all": True})
        except BridgeError:
            pass
        return st
    if ds:
        st["dialogs"] = ds
    if st.get("command"):
        K.record_command(st)
        mem = K.remembered_for_command(st["command"]["key"])
        if mem:
            st["remembered"] = mem
    elif not st.get("modal_dialogs"):
        st["note"] = ("No panel or dialog appeared. The command may act immediately (check with read tools), "
                      "may need a selection first, or may use a different key (see list_commands).")
    return with_project_notes(st)


def t_command_ui_inspect(a):
    st = ui_state(a.get("scope"), bool(a.get("include_hidden")), a.get("include_text", True))
    if st.get("modal_dialogs"):
        st["dialogs"] = dialogs_snapshot(st)
    if st.get("command") and not a.get("scope"):
        K.record_command(st)
        mem = K.remembered_for_command(st["command"]["key"])
        if mem:
            st["remembered"] = mem
    return st


FILL_SETTLE_S = 0.8

# Field orders TBC cannot handle: (command key, fields that need `required` to be filled first, required field)
FILL_ORDER_GUARDS = [
    ("DivideArea", ("origin", "end point"), "Area to Divide"),  # TBC crashed when Origin was typed with no area set
]


def guard_fill(pairs):
    st = ui_state(include_text=False)
    key = (st.get("command") or {}).get("key")
    for cmd, needs, req in FILL_ORDER_GUARDS:
        if key != cmd or not any(str(p[0]).strip().lower() in needs for p in pairs):
            continue
        cur = [f for f in st.get("fields", []) if (f.get("label") or "") == req]
        if any(str(p[0]) == req for p in pairs) or (cur and str(cur[0].get("value") or "").strip()):
            continue
        raise BridgeError("%s: fill '%s' first (it is empty). Typing %s before it is set has crashed TBC."
                          % (cmd, req, "/".join(needs)))


def t_command_ui_fill(a):
    wait_idle()
    vals = a.get("values") or {}
    pairs = list(vals.items()) if isinstance(vals, dict) else [list(p) for p in vals]
    guard_fill(pairs)
    r = run_ipy("command_ui", "fill", {"values": pairs, "press": a.get("press"), "scope": a.get("scope"),
                                       "stop_on_error": a.get("stop_on_error", True)})
    # let TBC finish redrawing live previews (rubber bands, highlights) before the next scripted step;
    # three graphics-module crashes happened during previews under fast scripted input
    time.sleep(FILL_SETTLE_S)
    if r.get("pressed"):
        r["after"] = ui_after(float(a.get("wait_seconds", 1.0)))
    return r


def t_command_ui_click(a):
    wait_idle()
    r = run_ipy("command_ui", "click", {"button": a["button"], "scope": a.get("scope")})
    r["after"] = ui_after(float(a.get("wait_seconds", 1.0)))
    return r


def view_covered_by_other_app():
    """Sample a grid of points over the view's screen area; if any top-level window there belongs to another
    process, return a description (privacy: never screenshot other applications)."""
    if os.name != "nt":
        return None
    import ctypes
    import ctypes.wintypes as W
    u = ctypes.windll.user32
    rc = run_ipy("view", "screen_rect", {})
    pid = (read_info() or {}).get("pid")
    u.WindowFromPoint.restype = W.HWND
    u.GetAncestor.restype = W.HWND
    for fx in (0.05, 0.25, 0.5, 0.75, 0.95):
        for fy in (0.05, 0.25, 0.5, 0.75, 0.95):
            x = int(rc["left"] + rc["width"] * fx)
            y = int(rc["top"] + rc["height"] * fy)
            h = u.WindowFromPoint(W.POINT(x, y))
            if not h:
                return "nothing visible at %d,%d" % (x, y)
            p = W.DWORD()
            u.GetWindowThreadProcessId(u.GetAncestor(h, 2) or h, ctypes.byref(p))
            if pid and p.value != pid:
                return "another application's window at %d%%,%d%% of the view" % (fx * 100, fy * 100)
    return None


def t_view(a):
    act = a.get("action", "info")
    args = {"units": a.get("units", "display")}
    if act == "info":
        return run_ipy("view", "info", args)
    if act == "screenshot":
        covered = view_covered_by_other_app()
        if covered:
            raise BridgeError("TBC's view is covered by another window (%s), so no screenshot was taken - it would "
                              "capture that window's content instead. Ask the user to bring TBC to the front." % covered)
        r = run_ipy("view", "screenshot", dict(args, max_width=int(a.get("max_width", 1400))))
        r["_image_path"] = r["path"]
        return r
    if act == "set_extents":
        if a.get("zoom_extents"):
            return run_ipy("view", "set_extents", dict(args, zoom_extents=True))
        return run_ipy("view", "set_extents", dict(args, min=a["min"], max=a["max"]))
    raise BridgeError("action must be info, screenshot or set_extents")


def post_click(hwnd, x, y):
    """Deliver a genuine left click to a window's client point (TBC sees it exactly like a user click)."""
    import ctypes
    u = ctypes.windll.user32
    lp = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)
    u.PostMessageW(hwnd, 0x0201, 0x0001, lp)  # WM_LBUTTONDOWN, MK_LBUTTON
    u.PostMessageW(hwnd, 0x0202, 0x0000, lp)  # WM_LBUTTONUP


def t_ui_grid(a):
    act = a.get("action", "read")
    base = {"scope": a.get("scope"), "grid": a.get("grid")}
    if act == "read":
        return run_ipy("command_ui", "grid_read", dict(base, where=a.get("where"), limit=a.get("limit", 200)))
    if act == "set":
        cur = run_ipy("command_ui", "grid_read", dict(base, where=a["row"] if isinstance(a["row"], dict) else None, limit=500))
        rows = cur["rows"] if isinstance(a["row"], dict) else [x for x in cur["rows"] if x["_row"] == a["row"]]
        col = next((c for c in cur["columns"] if a["column"].lower() in (c["name"].lower(), (c["header"] or "").lower())), None)
        if rows and col and col["type"] == "CheckBoxColumn":
            # TBC only commits checkbox changes from a real click: toggle by clicking if needed
            want = a["value"] if isinstance(a["value"], bool) else str(a["value"]).lower() in ("1", "true", "yes", "on")
            if bool(rows[0].get(col["name"])) == want:
                return {"column": col["name"], "now": want, "changed": False}
            pt = run_ipy("command_ui", "grid_click", dict(base, row=a["row"], column=a["column"]))
            r = {"column": col["name"], "clicked": True}
            r["after"] = ui_after(float(a.get("wait_seconds", 0.8)))
            now = run_ipy("command_ui", "grid_read", dict(base, limit=500))["rows"][pt["row"]].get(col["name"])
            r["now"] = now
            if now != want:
                r["warning"] = "value did not change; TBC may have refused (check 'after')"
            return r
        r = run_ipy("command_ui", "grid_set", dict(base, row=a["row"], column=a["column"], value=a["value"]))
        r["after"] = ui_after(float(a.get("wait_seconds", 0.8)))
        return r
    if act == "click":
        # scroll the cell into view first and let the grid redraw, THEN click (a click in the same instant as the
        # scroll only selected the cell; Layer Manager's red X then did nothing)
        run_ipy("command_ui", "grid_cell_point", dict(base, row=a["row"], column=a["column"]))
        time.sleep(0.8)
        pt = run_ipy("command_ui", "grid_click", dict(base, row=a["row"], column=a["column"]))
        r = {"clicked": {"row": pt["row_values"], "column": pt["column"]}}
        r["after"] = ui_after(float(a.get("wait_seconds", 1.0)))
        return r
    raise BridgeError("action must be read, set or click")


def t_tbc_dialogs(a):
    act = a.get("action", "list")
    if act == "list":
        return {"dialogs": dialogs_snapshot()}
    if act == "dismiss":
        return {"actions": safe_dismiss()}
    if act == "click":
        btn = a["button"]
        if not a.get("force") and btn.strip().lower() not in SAFE_BUTTONS:
            lic = [x for x in dialogs_snapshot() if is_license_dialog(x)]
            if lic:
                raise BridgeError("Refusing to press '%s' on a license popup (%s). Use action=dismiss to back out; "
                                  "only the user should change licensing." % (btn, lic[0].get("title")))
        if a.get("native"):
            r = native_dialogs(click=btn)
        else:
            try:
                r = run_ipy("command_ui", "click", {"button": btn, "scope": "dialog:%d" % int(a.get("index", 0))})
            except BridgeError as ex:
                if "No modal dialog" not in str(ex) and "No button" not in str(ex):
                    raise
                r = native_dialogs(click=btn)
        r["after"] = ui_after(float(a.get("wait_seconds", 1.0)))
        return r
    if act == "fill":
        return t_command_ui_fill(dict(a, scope="dialog:%d" % int(a.get("index", 0))))
    if act == "file":
        r = native_dialogs(set_file=a["path"])
        r["after"] = ui_after(float(a.get("wait_seconds", 1.5)))
        return r
    raise BridgeError("action must be list, click, fill, file or dismiss")


# ---------------------------------------------------------------------------
# Knowledge tools
# ---------------------------------------------------------------------------
def t_skills(a):
    act = a.get("action", "list")
    if act == "list":
        return {"knowledge_dir": K.ROOT, "skills": K.list_skills(a.get("category"))}
    if act == "search":
        return {"results": annotate_license(K.search(a["query"], a.get("kinds"), int(a.get("limit", 15))))}
    if act == "read":
        text = K.read_skill(a["name"])
        lm = licensed_map()
        bad = sorted(set(m for m in CMD_REF_RE.findall(text) if lm.get(m.lower()) is False)) if lm else []
        if bad:
            text = ("NOTE: this skill mentions commands that THIS user's TBC license does not include: %s. "
                    "Skills may have been written on a machine with a different license.\n\n" % ", ".join(bad)) + text
        return text
    if act in ("save", "append_version_section"):
        try:
            tbc_version()  # stamp new knowledge with the release actually running
        except BridgeError:
            pass
    if act == "save":
        return K.save_skill(a["name"], a.get("category", "general"), a.get("description", ""), a["body"],
                            bool(a.get("requires_write")), a.get("parameters"), bool(a.get("overwrite")))
    if act == "append_version_section":
        return K.append_version_section(a["name"], a["body"], a.get("release"))
    raise K.KnowledgeError("action must be list, search, read, save or append_version_section")


def _compile_check(code):
    try:
        call_bridge("execute_python", {"code": "import json as _j\ncompile(_j.loads(%r), '<script>', 'exec')" % json.dumps(code),
                                       "transaction": False}, timeout=30)
        return "compiled OK in TBC's IronPython"
    except BridgeError as ex:
        if "not running" in str(ex) or "not reachable" in str(ex):
            compile(code, "<script>", "exec")
            return "TBC not running: syntax checked with CPython only (IronPython 3.4 may still differ)"
        raise


def t_script(a):
    act = a.get("action", "list")
    if act == "list":
        return {"knowledge_dir": K.ROOT, "scripts": K.list_scripts()}
    if act == "read":
        return K.read_script(a["name"])
    if act == "delete":
        return K.delete_script(a["name"])
    if act == "save":
        try:
            tbc_version()
        except BridgeError:
            pass
        text = K.build_script(a["name"], a.get("description", ""), a.get("mode", "read"), a.get("parameters"), a["code"])
        meta, body = K.parse_script(text)
        check = _compile_check(body)
        r = K.save_script(a["name"], text, bool(a.get("overwrite")))
        r["check"] = check
        return r
    if act == "run":
        meta, body = K.parse_script(K.read_script(a["name"]))
        bound = K.bind_args(meta, a.get("args"))
        code = "import json as _j\nargs = _j.loads(%r)\n" % json.dumps(bound) + body
        r = call_bridge("execute_python", {"code": code, "transaction": meta.get("mode") == "write"})
        r["script"] = meta["name"]
        r["script_version"] = meta.get("script_version", 1)
        r["args"] = bound
        try:
            note = K.version_note(meta.get("tbc_versions") or [K.BASELINE_RELEASE]) if tbc_version() else None
        except BridgeError:
            note = None
        if note:
            r["version_note"] = note + " If it works, save it again (tbc_script save overwrite=true) to record this release."
        return r
    raise K.KnowledgeError("action must be list, read, save, run or delete")


EXISTS_CODE = r"""
from System import UInt32
result = [int(s) for s in args if prj.Concordance.Lookup(UInt32(int(s))) is not None]
"""
LAYER_TYPE_CODE = r"""
from System import UInt32
result = [int(s) for s in args if prj.Concordance.Lookup(UInt32(int(s))).GetType().Name == 'Layer']
"""


IMPORT_RECORD_CODE = r"""
from System import UInt32
out = []
for s in args:
    o = prj.Concordance.Lookup(UInt32(s))
    if o is not None and o.GetType().Name == 'FileProperties':
        out.append({'serial': s, 'file': str(getattr(o, 'Name', '') or '')})
result = out
"""


def t_delete_entities(a):
    """Delete through TBC's own Delete command (select + Delete, like the Delete key).
    Raw container removal (the old way) skipped TBC's cleanup and is the prime suspect for three HOOPS
    graphics-engine crashes on 2026-10-13, so it is no longer used."""
    serials = [int(s) for s in a["serials"]]
    if not serials:
        return {"deleted": []}
    existing = call_bridge("execute_python", {"code": "args = %r\n" % serials + EXISTS_CODE, "transaction": False})["result"]
    missing = sorted(set(serials) - set(existing))
    # layers work too: selecting a layer and running TBC's Delete command removes it (verified 2026-10-13)
    if not existing:
        return {"deleted": [], "not_found": missing}
    if not a.get("allow_import_records"):
        types = call_bridge("execute_python", {"code": "args = %r\n" % existing + IMPORT_RECORD_CODE, "transaction": False})["result"]
        if types:
            # TBC 2026.10: deleting an import's FileProperties record left a broken imported-file entry and the next
            # import failed inside TBC (error report 2026-10-14: ImportCommandViewModel.UpdateFiles NullReference).
            raise BridgeError("Refusing to delete import record(s) %s: on TBC 2026.10 that broke the next import. Delete the "
                              "imported data instead, or pass allow_import_records=true if the user asks." % types)
    wait_idle()
    call_bridge("set_selection", {"serials": existing})
    check_license("delete")
    pace_command()
    call_bridge("run_command", {"key": "delete"})
    time.sleep(1.0)
    wait_idle()
    left = call_bridge("execute_python", {"code": "args = %r\n" % existing + EXISTS_CODE, "transaction": False})["result"]
    try:
        call_bridge("set_selection", {"serials": []})
    except BridgeError:
        pass
    if left:
        ds = dialogs_snapshot()
        raise BridgeError("TBC's Delete command left %d of %d objects (serials %s). Popups: %s" % (
            len(left), len(existing), left[:20], [(d.get("title"), d.get("message")) for d in ds]))
    return {"deleted": existing, "not_found": missing, "method": "TBC Delete command (undo with Ctrl+Z)"}


LINE_ELEV_CODE = r"""
import math
l = bridge.lookup(prj, args["serial"])
f = 1.0 if args.get("units") == "meters" else bridge.factor(prj)
zs, dist, prev = [], 0.0, None
for i in range(min(int(l.ElementCount), 2000)):
    p = l.ElementAt(i).Position
    if prev is not None:
        dist += math.hypot(p.X - prev.X, p.Y - prev.Y)
    prev = p
    r = clr.Reference[Point3D](Point3D(p.X, p.Y, p.Z))
    l.UpdateSnapElevation(r, dist)
    zs.append(r.Value.Z * f if r.Value.Z == r.Value.Z else None)
result = zs
"""


def t_get_entity(a):
    """get_entity + effective linestring elevations: TBC stores e.g. Change Elevation results as a vertical
    element (vertex z stays undefined), so evaluate the elevation along the line at each vertex."""
    e = call_bridge("get_entity", a)
    vs = e.get("vertices")
    if vs and e.get("type", "").endswith("Linestring") and any(v.get("z") is None for v in vs):
        try:
            zs = call_bridge("execute_python", {"code": "args = %r\n" % {"serial": a["serial"], "units": a.get("units", "display")} + LINE_ELEV_CODE,
                                                "transaction": False})["result"]
            for v, z in zip(vs, zs):
                if v.get("z") is None and z is not None:
                    v["z"] = z
                    v["z_source"] = "vertical profile"
        except BridgeError:
            pass
    return e


NEXT_ID_CODE = r"""
mx = 0
names = set()
for pt in TbcPoint.GetAllPoints(prj):
    n = str(pt.Name)
    names.add(n)
    if n.isdigit():
        mx = max(mx, int(n))
result = {"max_numeric": mx, "taken": [n for n in args if n in names]}
"""


def t_create_points(a):
    """Numeric IDs by default (user preference); feature codes go through the verified Create Point panel."""
    pts = [dict(p) for p in a["points"]]
    units = a.get("units", "display")
    wanted = [str(p["name"]) for p in pts if p.get("name") not in (None, "")]
    info = call_bridge("execute_python", {"code": "args = %r\n" % wanted + NEXT_ID_CODE, "transaction": False})["result"]
    if info["taken"] and not a.get("allow_duplicates"):
        raise BridgeError("Point ID(s) already exist: %s. Omit 'name' to get the next free numbers, or pass "
                          "allow_duplicates=true." % info["taken"][:20])
    nxt = int(a.get("start_id") or info["max_numeric"] + 1)
    for p in pts:
        if p.get("name") in (None, ""):
            p["name"] = str(nxt)
            nxt += 1
    if not any(p.get("feature_code") for p in pts):
        r = call_bridge("create_points", {"points": [{k: v for k, v in p.items() if k != "feature_code"} for p in pts],
                                          "units": units})
        r["method"] = "api (one undo step)"
        return r
    # feature codes -> Create Point panel (TBC's own code processing)
    f = 1.0
    if units == "meters":
        f = call_bridge("project_info")["meters_to_display_factor"]
    layers = set(p["layer"] for p in pts if p.get("layer"))
    for l in layers:
        call_bridge("create_layer", {"name": l})
    st = t_command_ui_open({"key": "addpoint"})
    if not st.get("command"):
        raise BridgeError("Create Point panel did not open: %s" % json.dumps(st)[:400])
    made, problems = [], []
    try:
        for p in pts:
            vals = [["Point ID", p["name"]], ["Feature code", p.get("feature_code") or ""]]
            if p.get("layer"):
                vals.append(["Layer", p["layer"]])
            vals += [["Northing", "%.4f" % (p["northing"] * f)], ["Easting", "%.4f" % (p["easting"] * f)]]
            if p.get("elevation") is not None:
                vals.append(["Elevation", "%.4f" % (p["elevation"] * f)])
            r = t_command_ui_fill({"values": vals, "press": "Add", "wait_seconds": 0.4})
            after = r.get("after", {})
            if r.get("errors") or after.get("dialogs") or after.get("field_status"):
                problems.append({"point": p["name"], "errors": r.get("errors"), "after": after})
                if after.get("dialogs"):
                    safe_dismiss(after["dialogs"])  # e.g. duplicate-ID warning -> No
            else:
                made.append(p["name"])
    finally:
        try:
            run_ipy("command_ui", "close", {})
        except BridgeError:
            pass
    return {"method": "Create Point panel (feature codes)", "created": len(made), "ids": made[:50] + (["..."] if len(made) > 50 else []),
            "problems": problems[:20]}


HELP_TOPIC_CODE = r"""
cl = TrimbleOffice.TheOffice.CommandProcessor.CommandList
k = args.lower()
result = str(getattr(cl[k], 'HelpTopic', '') or '') if cl.ContainsKey(k) else None
"""


def t_help(a):
    act = a.get("action", "search")
    if act == "search":
        return {"results": HELP.search(a["query"], int(a.get("limit", 15)))}
    if act == "read":
        tid = a.get("topic")
        if not tid and a.get("command"):
            tid = call_bridge("execute_python", {"code": "args = %r\n" % a["command"] + HELP_TOPIC_CODE, "transaction": False})["result"]
            if not tid:
                raise BridgeError("Command '%s' has no help topic" % a["command"])
        d = HELP.topic(tid, int(a.get("max_chars", 6000)))
        if not d:
            raise BridgeError("No help topic %s in %s" % (tid, HELP.HELP_DIR))
        return d
    raise BridgeError("action must be search or read")


# ---------------------------------------------------------------------------
# Import / Export (Home tab)
# ---------------------------------------------------------------------------
def _close_pane():
    try:
        run_ipy("command_ui", "close", {})
    except BridgeError:
        pass


def t_export(a):
    """Export through TBC's Export pane: category tab -> exporter -> data -> target file -> Export."""
    act = a.get("action", "export")
    t_command_ui_open({"key": "export"})
    try:
        if act == "formats":
            return {"formats": run_ipy("import_export", "export_formats", {"category": a.get("category")})}
        path = a.get("path") or ""
        if not os.path.isabs(path):
            raise BridgeError("path must be a full file path (the default would be the project folder)")
        if os.path.exists(path) and not a.get("overwrite"):
            raise BridgeError("%s already exists; pass overwrite=true to replace it" % path)
        chosen = run_ipy("import_export", "export_choose", {"category": a["category"], "format": a["format"]})
        time.sleep(FILL_SETTLE_S)
        st = ui_state(include_text=False)
        data_box = [f["id"] for f in st.get("fields", []) if "Selected:" in str(f.get("value"))]
        values = []
        if a.get("serials"):
            if not data_box:
                raise BridgeError("This exporter has no data selection box; fields: %s" % [f["id"] for f in st.get("fields", [])])
            values.append([data_box[0], list(a["serials"])])
        values.append(["TargetFileBox", path])
        values += [list(p) for p in (a.get("settings") or [])]
        r = t_command_ui_fill({"values": values, "press": "Export", "wait_seconds": float(a.get("wait_seconds", 3))})
        wait_idle()
        size = os.path.getsize(path) if os.path.exists(path) else 0
        return {"exported": size > 0, "path": path, "bytes": size, "exporter": chosen, "fill": r}
    finally:
        _close_pane()


def t_import(a):
    """Import through TBC's Import pane: scan a folder (shows the importer TBC picked per file), then import."""
    act = a.get("action", "scan")
    folder = a.get("folder") or ""
    if not os.path.isdir(folder):
        raise BridgeError("folder must be an existing folder: %r" % folder)
    t_command_ui_open({"key": "import"})
    done_ok = False
    try:
        st = run_ipy("import_export", "import_folder", {"folder": folder})
        t0 = time.time()
        while (st["scanning"] or not st["files"]) and time.time() - t0 < 60:
            time.sleep(0.5)
            st = run_ipy("import_export", "import_state", {})
        if act == "scan":
            return st
        if not a.get("confirm"):
            raise BridgeError("Importing changes the project and TBC copies each file into the project folder. "
                              "Check the importer shown for each file (action=scan), ask the user, then call again with confirm=true.")
        files = a.get("files") or []
        if not files:
            raise BridgeError("files: list the file names to import (from action=scan)")
        # (DXF import was briefly on hold on 2026-10-14; the real cause was deleted import records - see
        # delete_entities - and a DXF import verified fine once that stopped.)
        st = run_ipy("import_export", "import_select", {"files": files})
        time.sleep(FILL_SETTLE_S)
        r = t_command_ui_click({"button": "Import", "wait_seconds": float(a.get("wait_seconds", 3))})
        steps = []
        # custom/CSV formats open the 'Import Format Editor' wizard; its Import button imports with that format
        for d in dialogs_snapshot():
            if (d.get("title") or "").startswith("Import Format Editor") and "Import" in (d.get("buttons") or []):
                steps.append(t_tbc_dialogs({"action": "click", "index": d["index"], "button": "Import"}))
        waited = wait_idle()
        left = [d for d in dialogs_snapshot() if not is_busy_dialog(d)]
        errors = [d for d in left if is_error_dialog(d)]
        for d in errors:
            log_tbc_error(d, "tbc_import")
        done_ok = not errors
        return {"imported": st["selected"],
                "importers": {f["name"]: f["importer"] for f in st["files"] if f["name"] in st["selected"]},
                "after": r.get("after"), "format_editor": steps, "waited_for_compute_s": waited,
                "popups_left": left, "errors": errors,
                "note": "TBC copied the imported file(s) into the project folder."}
    finally:
        if act == "scan" or done_ok or not [d for d in dialogs_snapshot() if is_error_dialog(d)]:
            _close_pane()


# ---------------------------------------------------------------------------
# License profile: which commands THIS user's license allows (users differ)
# ---------------------------------------------------------------------------
# License profiles are per-user, per-machine data: they live OUTSIDE the repo/knowledge base, in
# %LOCALAPPDATA%\TBC-MCP\license (override the base folder with TBC_MCP_USER_DIR), so they are never shared.
USER_DIR = os.environ.get("TBC_MCP_USER_DIR") or os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "TBC-MCP")
LICENSE_DIR = os.path.join(USER_DIR, "license")
_lic = {"profile": None, "checked": 0.0}


def license_profile(refresh=False):
    """The current license profile. Built when the MCP server starts, saved to
    %LOCALAPPDATA%\\TBC-MCP\\license\\<fingerprint>.json (this machine only, never in the repo).
    Profiles are keyed by a hash of the license key + licensed features; no user names or emails are stored."""
    now = time.time()
    if _lic["profile"] is None:
        refresh = True  # every new MCP server instance rebuilds the profile (takes ~0.5 s), so it is always current
    if _lic["profile"] is not None and not refresh and now - _lic["checked"] < 600:
        return _lic["profile"]
    fp = run_ipy("license", "fingerprint", {})["fingerprint"]
    path = os.path.join(LICENSE_DIR, fp + ".json")
    prof = None
    if os.path.exists(path) and not refresh:
        try:
            with open(path, "r", encoding="utf-8") as f:
                prof = json.load(f)
        except ValueError:
            prof = None
    if prof is None:
        log("building license profile %s for this MCP instance" % fp)
        prof = run_ipy("license", "profile", {})
        prof["created"] = time.strftime("%Y-%m-%d %H:%M:%S")
        cmds = prof.get("commands", {})
        prof["summary"] = {"commands_total": len(cmds),
                           "commands_licensed": sum(1 for v in cmds.values() if v.get("licensed")),
                           "commands_not_licensed": sum(1 for v in cmds.values() if v.get("licensed") is False),
                           "features_licensed": len(prof.get("features_licensed", [])),
                           "features_not_licensed": len(prof.get("features_unlicensed", []))}
        os.makedirs(LICENSE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(prof, f, indent=1, ensure_ascii=False)
        prof["_new"] = True
    _lic["profile"], _lic["checked"] = prof, now
    return prof


def licensed_map():
    """{command key (lower): True/False/None} from the cached profile, or {} if TBC isn't reachable."""
    try:
        return dict((k.lower(), v.get("licensed")) for k, v in license_profile().get("commands", {}).items())
    except BridgeError:
        return {}


def t_license(a):
    act = a.get("action", "summary")
    p = license_profile(refresh=(act == "refresh"))
    cmds = p.get("commands", {})
    if act in ("summary", "refresh"):
        return {"fingerprint": p.get("fingerprint"), "profile_created": p.get("created"), "new_profile": bool(p.get("_new")),
                "key_type": p.get("key_type"), "subscription_expires": p.get("subscription_expires"),
                "maintenance_expires": p.get("maintenance_expires"), "summary": p.get("summary"),
                "features_licensed": [(f.get("name"), f.get("expires")) for f in p.get("features_licensed", [])],
                "features_not_licensed": p.get("features_unlicensed", []),
                "note": "Command availability is also checked live before every command runs."}
    if act == "check":
        out = {}
        live = run_ipy("command_ui", "license", {"keys": a["keys"]})
        for k in a["keys"]:
            out[k] = live.get(k)
        return {"commands": out}
    if act == "unlicensed":
        f = (a.get("contains") or "").lower()
        rows = [{"key": k, "caption": v.get("caption"), "needs_any_of": v.get("needs_any_of")}
                for k, v in sorted(cmds.items()) if v.get("licensed") is False and (not f or f in k.lower() or f in (v.get("caption") or "").lower())]
        return {"count": len(rows), "commands": rows[:int(a.get("limit", 200))]}
    raise BridgeError("action must be summary, refresh, check or unlicensed")


CMD_REF_RE = re.compile(r"`([A-Za-z][A-Za-z0-9_.]{2,60})`")


def annotate_license(results):
    """Flag knowledge hits that rely on commands this user's license doesn't include."""
    lm = licensed_map()
    if not lm:
        return results
    for h in results:
        if h.get("type") == "command":
            h["licensed"] = lm.get(str(h.get("key", "")).lower())
        elif h.get("type") == "lesson":
            if h.get("topic", "").lower() in lm:
                h["licensed"] = lm.get(h["topic"].lower())
        elif h.get("type") == "skill":
            try:
                body = K.read_skill(h["name"])
            except K.KnowledgeError:
                continue
            bad = sorted(set(m for m in CMD_REF_RE.findall(body) if lm.get(m.lower()) is False))
            if bad:
                h["unlicensed_commands_mentioned"] = bad
    return results


_ver = {"value": None}
VERSION_CODE = r"""
from System.Diagnostics import Process, FileVersionInfo
p = Process.GetCurrentProcess().MainModule.FileName
result = {'exe': p, 'build': str(FileVersionInfo.GetVersionInfo(p).ProductVersion)}
"""


def tbc_version(refresh=False):
    """{'release': '2026.10', 'build': '44.0.9666.28609'} of the running TBC. The build comes from the running exe;
    the release name (e.g. 26.10 -> 2026.10) from Windows' install record for that folder. Cached per server run."""
    if _ver["value"] and not refresh:
        return _ver["value"]
    info = call_bridge("execute_python", {"code": VERSION_CODE, "transaction": False}, timeout=30)["result"]
    release = None
    try:
        import winreg
        folder = os.path.dirname(info["exe"]).rstrip("\\").lower()
        for root in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                     r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
            try:
                k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root)
            except OSError:
                continue
            for i in range(winreg.QueryInfoKey(k)[0]):
                try:
                    sk = winreg.OpenKey(k, winreg.EnumKey(k, i))
                    name = winreg.QueryValueEx(sk, "DisplayName")[0]
                    loc = str(winreg.QueryValueEx(sk, "InstallLocation")[0]).rstrip("\\").lower()
                    if name.startswith("Trimble Business Center") and "help" not in name.lower() and loc == folder:
                        dv = str(winreg.QueryValueEx(sk, "DisplayVersion")[0])
                        release = ("20" + dv) if re.match(r"^\d\d\.\d+$", dv) else dv
                except OSError:
                    continue
    except ImportError:
        pass
    v = {"release": release or ("build " + info["build"]), "build": info["build"]}
    _ver["value"] = v
    K.set_tbc_version(v["release"], v["build"])
    return v


def t_bridge_status(a):
    r = call_bridge("ping", timeout=10)
    try:
        v = tbc_version()
        r["tbc"] = dict(v, knowledge_baseline=K.BASELINE_RELEASE,
                        note=None if v["release"] == K.BASELINE_RELEASE else
                        "The knowledge base was verified on TBC %s. Check recipes still work on %s; ADD a section for %s "
                        "where they differ, never delete the %s information." % (K.BASELINE_RELEASE, v["release"], v["release"], K.BASELINE_RELEASE))
    except BridgeError as ex:
        r["tbc"] = {"error": str(ex)[:200]}
    try:
        p = license_profile()
        r["license"] = {"fingerprint": p.get("fingerprint"), "new_profile": bool(p.get("_new")), "summary": p.get("summary"),
                        "subscription_expires": p.get("subscription_expires"),
                        "hint": "tbc_license action=summary for features; unlicensed commands are refused automatically"}
    except BridgeError as ex:
        r["license"] = {"error": str(ex)[:200]}
    return r


def t_preferences(a):
    act = a.get("action", "list")
    if act == "list":
        return {"preferences": K.list_prefs(), "file": K.PREFS}
    if act == "add":
        return K.add_pref(a["text"], a.get("topic"))
    if act == "update":
        return K.update_pref(a["id"], a["text"])
    if act == "remove":
        return K.remove_pref(a["id"])
    raise K.KnowledgeError("action must be list, add, update or remove")


# ---------------------------------------------------------------------------
# Project knowledge shared with Civil 3D MCP and Project Analyzer (projects.py)
# ---------------------------------------------------------------------------
_active = {"path": None, "at": 0.0}
ACTIVE_PATH_CODE = "result = str(prj.ProjectName)"   # TBC 2026: ProjectName is the full .vce path


def active_project_path(refresh=False):
    """Full path of the project open in TBC, or None (no project, unsaved, or TBC unreachable). Cached for 30 s so
    attaching project notes costs at most one small bridge call per half minute."""
    if not refresh and time.time() - _active["at"] < 30:
        return _active["path"]
    try:
        path = call_bridge("execute_python", {"code": ACTIVE_PATH_CODE, "transaction": False}, timeout=15).get("result")
    except BridgeError:
        path = None
    remember_active_path(path)
    return _active["path"]


def remember_active_path(path):
    _active["path"] = path if path and os.path.isabs(str(path)) else None
    _active["at"] = time.time()


def with_project_notes(result, path=None):
    """Adds the open project's shared notes to a result, once per project per server run."""
    if not isinstance(result, dict):
        return result
    try:
        notes = P.notes_once(path or active_project_path())
    except Exception:
        notes = None  # project notes are advice; never fail a call because of them
    if notes:
        result["project_notes"] = notes
    return result


def t_project_info(a):
    info = call_bridge("project_info")
    if isinstance(info, dict):
        remember_active_path(info.get("path"))
        with_project_notes(info, _active["path"])
    return info


def t_execute_python(a):
    r = call_bridge("execute_python", a)
    if isinstance(r, dict):
        lessons = K.lessons_relevant_to(a.get("code", ""))
        if lessons:
            r["related_lessons"] = lessons
        with_project_notes(r)
    return r


def t_project_notes(a):
    act = a.get("action", "list")
    name = a.get("project")
    if act == "unlink":
        return P.unlink(name, a.get("folder"))
    # a named project needs no TBC; otherwise the project open in TBC picks it (link: its folder is the default)
    path = None if name and act != "link" else active_project_path(refresh=True)
    if act == "list":
        return P.list_notes(name, path)
    if act == "link":
        if not name:
            raise K.KnowledgeError("project (a name) is required to link a folder")
        return P.link(name, a.get("folder"), path)
    if act == "add":
        return P.add_note(a.get("note"), name, path)
    if act == "update":
        return P.update_note(a.get("id"), a.get("note"), name, path)
    if act == "remove":
        return P.remove_note(a.get("id"), name, path)
    if act == "files":
        return P.project_files(name, path)
    if act == "read":
        return P.read_file(a.get("file"), name, path, int(a.get("max_chars", P.MAX_READ_CHARS)))
    raise K.KnowledgeError("action must be list, link, unlink, add, update, remove, files or read")


def t_memory(a):
    act = a.get("action", "list")
    if act in ("add", "delete"):
        try:
            tbc_version()  # lessons are stamped with (and protected by) the running release
        except BridgeError:
            pass
    if act == "add":
        rec = K.add_lesson(a["text"], a.get("topic") or a.get("command"), a.get("tags"))
        if rec.get("action") == "unchanged":
            return rec
        if a.get("command"):
            K.add_command_note(a["command"], a["text"])
        hit = [w for w in DANGER_WORDS if w in a["text"].lower()]
        if hit:
            rec["note"] = ("This lesson contains %s: opening command '%s' will now require confirm=true. If that is not "
                           "intended, delete it and reword." % (hit, rec["topic"]))
        return rec
    if act == "search":
        return {"results": K.search(a["query"], ["lesson", "command"], int(a.get("limit", 20)))}
    if act == "list":
        return {"lessons": K.list_lessons(a.get("topic"))}
    if act == "delete":
        return K.delete_lesson(a["id"])
    raise K.KnowledgeError("action must be add, search, list or delete")


# ---------------------------------------------------------------------------
# SDK documentation search (offline, from the Macros SDK XML files)
# ---------------------------------------------------------------------------
_doc_index = None


def load_docs():
    global _doc_index
    if _doc_index is not None:
        return _doc_index
    rows = []
    for fn in glob.glob(os.path.join(SDK_DOCS, "*.xml")):
        try:
            root = ET.parse(fn).getroot()
        except Exception:
            continue
        asm = root.findtext("assembly/name")
        if not asm:
            continue
        for m in root.iter("member"):
            s = m.find("summary")
            summary = " ".join("".join(s.itertext()).split()) if s is not None else ""
            params = ["%s: %s" % (p.get("name"), " ".join("".join(p.itertext()).split())) for p in m.findall("param")]
            r = m.find("returns")
            rows.append((asm, m.get("name", ""), summary, params,
                         " ".join("".join(r.itertext()).split()) if r is not None else ""))
    _doc_index = rows
    log("indexed %d SDK doc members from %s" % (len(rows), SDK_DOCS))
    return rows


def search_docs(query, kind=None, limit=40, detail=False):
    rows = load_docs()
    if not rows:
        return "No SDK XML docs found in %s (set TBC_SDK_DOCS)." % SDK_DOCS
    try:
        pat = re.compile(query, re.I)
    except re.error:
        pat = re.compile(re.escape(query), re.I)
    kinds = {"type": "T:", "method": "M:", "property": "P:", "field": "F:", "event": "E:"}
    prefix = kinds.get(kind) if kind else None
    out, total = [], 0
    for asm, name, summary, params, ret in rows:
        if prefix and not name.startswith(prefix):
            continue
        if not (pat.search(name) or (detail and pat.search(summary))):
            continue
        total += 1
        if len(out) < limit:
            line = "[%s] %s" % (asm, name)
            if summary:
                line += "\n    " + summary[:400]
            if detail:
                for p in params:
                    line += "\n    param " + p[:200]
                if ret:
                    line += "\n    returns " + ret[:200]
            out.append(line)
    head = "%d match(es)%s. Note: docs are for SDK v41 (TBC 2024); verify against the live TBC with execute_python + dir()." % (
        total, "" if total <= limit else ", showing first %d" % limit)
    return head + "\n\n" + "\n".join(out)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------
UNITS = {"type": "string", "enum": ["display", "meters"], "default": "display",
         "description": "'display' = the project's display units (default), 'meters' = TBC internal units."}


def obj(props, required=None):
    s = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        s["required"] = required
    return s


TOOLS = [
    # name, description, schema, handler(args) -> result, annotations
    ("bridge_status", "Check whether the TBC bridge macro is running and reachable; also loads (or on first use builds) this user's license profile.",
     obj({}), t_bridge_status, {"readOnlyHint": True}),
    ("project_info", "Summary of the project open in TBC: name, file, display units, point/layer counts, modified flag. "
     "The first time per project it also returns the job's shared project notes (project_notes), if any.",
     obj({}), t_project_info, {"readOnlyHint": True}),
    ("list_entities", "List graphical objects in the project (recursively through containers) with serial, type, name and layer. "
     "Also returns counts by type. Use filters and paging for big projects.",
     obj({"type_contains": {"type": "string", "description": "Case-insensitive substring of the type name, e.g. 'Linestring', 'Model3D', 'Point'."},
          "name_contains": {"type": "string"},
          "layer": {"type": "string", "description": "Exact layer name."},
          "graphical_only": {"type": "boolean", "default": True},
          "limit": {"type": "integer", "default": 200}, "offset": {"type": "integer", "default": 0}}),
     lambda a: call_bridge("list_entities", a), {"readOnlyHint": True}),
    ("get_entity", "Inspect one object by serial number: all readable .NET properties, plus vertices for linestrings.",
     obj({"serial": {"type": "integer"}, "property_filter": {"type": "string", "description": "Only properties whose name contains this."},
          "units": UNITS}, ["serial"]),
     t_get_entity, {"readOnlyHint": True}),
    ("list_points", "List project points with name, easting/northing/elevation, layer and feature code.",
     obj({"name_contains": {"type": "string"}, "layer": {"type": "string"}, "units": UNITS,
          "limit": {"type": "integer", "default": 500}, "offset": {"type": "integer", "default": 0}}),
     lambda a: call_bridge("list_points", a), {"readOnlyHint": True}),
    ("list_layers", "List layers with visibility, lock state, color and member count.",
     obj({"with_counts": {"type": "boolean", "default": True}}), lambda a: call_bridge("list_layers", a), {"readOnlyHint": True}),
    ("list_surfaces", "List surfaces (TINs) with vertex/triangle counts and elevation range.",
     obj({"units": UNITS}), lambda a: call_bridge("list_surfaces", a), {"readOnlyHint": True}),
    ("surface_elevation", "Sample a surface's elevation at one or more X(easting)/Y(northing) locations.",
     obj({"surface": {"description": "Surface name or serial number.", "type": ["string", "integer"]},
          "points": {"type": "array", "items": obj({"x": {"type": "number"}, "y": {"type": "number"}}, ["x", "y"])},
          "units": UNITS}, ["surface", "points"]),
     lambda a: call_bridge("surface_elevation", a), {"readOnlyHint": True}),
    ("get_selection", "Objects currently selected in TBC.",
     obj({"limit": {"type": "integer", "default": 500}}), lambda a: call_bridge("get_selection", a), {"readOnlyHint": True}),
    ("set_selection", "Replace TBC's selection with the given serial numbers (empty list clears it).",
     obj({"serials": {"type": "array", "items": {"type": "integer"}}}, ["serials"]),
     lambda a: call_bridge("set_selection", a), {"readOnlyHint": False, "destructiveHint": False}),
    ("list_commands", "Search TBC's command list (keys usable with run_command / command_ui_open). Each entry says "
     "whether the current TBC license allows it (licensed=false commands are skipped automatically).",
     obj({"contains": {"type": "string"}, "limit": {"type": "integer", "default": 300}}),
     t_list_commands, {"readOnlyHint": True}),
    ("run_command", "Launch a TBC command by key (as the user would from the ribbon). Checks the license first and "
     "refuses unlicensed commands instead of triggering TBC's license popups. Runs asynchronously.",
     obj({"key": {"type": "string"}, "args": {"type": "array", "items": {}},
          "confirm": {"type": "boolean", "default": False, "description": "Required for commands the knowledge base marks as acting immediately; only after the user agreed."}}, ["key"]),
     t_run_command, {"readOnlyHint": False}),
    ("create_points", "Create points. Point IDs are numeric by default: omit 'name' and the next free numbers after "
     "the project's highest numeric ID are used (or start at start_id). Put descriptions in 'feature_code' (e.g. EP, "
     "TOE), not in the ID. Without codes: fast API path, one undo step. With codes: entered through TBC's Create Point "
     "panel so TBC processes the codes (slower, ~1 s per point). Existing IDs are refused unless allow_duplicates.",
     obj({"points": {"type": "array", "items": obj({
         "name": {"type": "string", "description": "Point ID; omit for the next free number."},
         "easting": {"type": "number"}, "northing": {"type": "number"},
         "elevation": {"type": "number", "description": "Omit for a 2D point."},
         "feature_code": {"type": "string", "description": "Description/feature code, e.g. 'EP' or 'GRID'."},
         "layer": {"type": "string", "description": "Layer name (created if missing)."}}, ["easting", "northing"])},
         "start_id": {"type": "integer"}, "allow_duplicates": {"type": "boolean", "default": False},
         "units": UNITS}, ["points"]),
     t_create_points, {"readOnlyHint": False, "destructiveHint": False}),
    ("create_linestring", "Create a straight-segment linestring from vertices (x=easting, y=northing, z optional).",
     obj({"vertices": {"type": "array", "minItems": 2, "items": obj({"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}}, ["x", "y"])},
          "name": {"type": "string"}, "layer": {"type": "string"}, "closed": {"type": "boolean", "default": False}, "units": UNITS},
         ["vertices"]),
     lambda a: call_bridge("create_linestring", a), {"readOnlyHint": False, "destructiveHint": False}),
    ("create_layer", "Create a layer (or return the existing one with that name).",
     obj({"name": {"type": "string"}, "color": {"type": "string", "description": "HTML color, e.g. '#FF0000' or 'Red'."}}, ["name"]),
     lambda a: call_bridge("create_layer", a), {"readOnlyHint": False, "destructiveHint": False}),
    ("set_properties", "Set .NET properties on one or more objects, e.g. {\"Name\": \"EP\", \"Layer\": \"Edges\"}. "
     "'Layer' accepts a layer name; '*Color' accepts HTML colors. Single undo step.",
     obj({"serial": {"type": "integer"}, "serials": {"type": "array", "items": {"type": "integer"}},
          "properties": {"type": "object"}}, ["properties"]),
     lambda a: call_bridge("set_properties", a), {"readOnlyHint": False, "destructiveHint": True}),
    ("delete_entities", "Delete objects by serial number through TBC's own Delete command (select + Delete), then confirm they are gone. Works for layers too (select the layer serial). Ctrl+Z in TBC restores them. Import records (FileProperties, "
     "one per imported file) are refused: deleting them broke the next import on TBC 2026.10 - delete the imported data instead.",
     obj({"serials": {"type": "array", "items": {"type": "integer"}},
          "allow_import_records": {"type": "boolean", "default": False, "description": "only if the user asks"}}, ["serials"]),
     t_delete_entities, {"readOnlyHint": False, "destructiveHint": True}),
    ("save_project", "Save the current TBC project to disk.",
     obj({}), lambda a: call_bridge("save_project"), {"readOnlyHint": False, "destructiveHint": True}),
    ("search_sdk_docs", "Search the TBC SDK API docs (offline). 'query' is a regex matched against member ids like "
     "'T:Trimble.Vce.Coordinates.Point' or 'M:...Point.CreatePoint(...)'. Use with execute_python to do things the other tools can't.",
     obj({"query": {"type": "string"}, "kind": {"type": "string", "enum": ["type", "method", "property", "field", "event"]},
          "search_summaries": {"type": "boolean", "default": False, "description": "Also match summary text and show params/returns."},
          "limit": {"type": "integer", "default": 40}}, ["query"]),
     lambda a: search_docs(a["query"], a.get("kind"), int(a.get("limit", 40)), bool(a.get("search_summaries"))),
     {"readOnlyHint": True}),
]

FIELD_VALUES = {"description": "Fields to fill, IN ORDER. Either an object {label_or_id: value} or a list of "
                               "[label_or_id, value] pairs. Match by the on-screen label (e.g. 'Northing', 'Point ID') "
                               "or the field id from command_ui_inspect. Type values as a user would (display units). Object-picker fields "
                               "(kind entity): pass {\"serial\": n} or an integer serial to link an existing object; any "
                               "string (e.g. a point ID like \"4700486\") is typed as text for TBC to interpret. "
                               "Checkboxes take true/false; dropdowns take the option text.",
                "type": ["object", "array"]}

TOOLS += [
    ("command_ui_open", "Start a TBC command (key from list_commands) and return its panel: every field with its "
     "on-screen label, current value, dropdown options, and the buttons. Also returns what was remembered about this "
     "command from earlier sessions, and records the panel layout to the knowledge base.",
     obj({"key": {"type": "string"}, "wait_seconds": {"type": "number", "default": 15},
          "confirm": {"type": "boolean", "default": False, "description": "Required for commands marked as acting immediately; only after the user agreed."},
          "include_hidden": {"type": "boolean", "default": False, "description": "Include fields in collapsed/hidden sections."}},
         ["key"]),
     t_command_ui_open, {"readOnlyHint": False, "destructiveHint": False}),
    ("command_ui_inspect", "Read the currently open command panel, a popup (scope='dialog:0'), or a docked pane "
     "(scope='pane:Layer Manager', 'pane:Properties', 'pane:Project Explorer', ...): fields, values, options, status "
     "messages, buttons, grids, any open popups, and the list of panes.",
     obj({"scope": {"type": "string", "description": "'command' (default), 'dialog:<index>' or 'pane:<title>'."},
          "include_hidden": {"type": "boolean", "default": False}, "include_text": {"type": "boolean", "default": True}}),
     t_command_ui_inspect, {"readOnlyHint": True}),
    ("command_ui_fill", "Fill fields in the open command panel like a user (types the value, then tabs out so TBC "
     "validates it), optionally press a button (e.g. 'Add', 'Apply', 'OK') afterwards. Returns each field's value as "
     "TBC now shows it plus what happened after the press (popups, status messages). Verify results with read tools.",
     obj({"values": FIELD_VALUES, "press": {"type": "string", "description": "Button text or id to press after filling."},
          "scope": {"type": "string"}, "stop_on_error": {"type": "boolean", "default": True},
          "wait_seconds": {"type": "number", "default": 1.0}}, ["values"]),
     t_command_ui_fill, {"readOnlyHint": False, "destructiveHint": True}),
    ("command_ui_click", "Press a button in the open command panel (or a popup with scope='dialog:0'), then report "
     "popups/status.",
     obj({"button": {"type": "string"}, "scope": {"type": "string"}, "wait_seconds": {"type": "number", "default": 1.0}},
         ["button"]),
     t_command_ui_click, {"readOnlyHint": False, "destructiveHint": True}),
    ("tbc_view", "What the user is looking at in TBC. action=info: the active Plan View's visible area (min/max/"
     "center/width/height, x=easting, y=northing) - use the center when the user says 'here' or 'where I'm "
     "looking'. action=screenshot: same plus an image of the view as the user sees it. action=set_extents: zoom to "
     "min/max (or zoom_extents=true) - e.g. to show the user a result; mention that you moved their view.",
     obj({"action": {"type": "string", "enum": ["info", "screenshot", "set_extents"], "default": "info"},
          "min": obj({"x": {"type": "number"}, "y": {"type": "number"}}, ["x", "y"]),
          "max": obj({"x": {"type": "number"}, "y": {"type": "number"}}, ["x", "y"]),
          "zoom_extents": {"type": "boolean", "default": False}, "units": UNITS,
          "max_width": {"type": "integer", "default": 1400}}),
     t_view, {"readOnlyHint": False, "destructiveHint": False}),
    ("ui_grid", "Work with tables (grids) inside TBC panels and panes, e.g. the Layer Manager "
     "(scope='pane:Layer Manager', opened with run_command layermanager). action=read lists columns and rows; "
     "set edits a cell (text, checkbox, dropdown) through the grid's normal editing; click delivers a genuine mouse "
     "click to one cell (for icon cells such as Layer Manager's red-X Delete column). Rows are matched by column "
     "values, e.g. row={\"LayerName\": \"MY_LAYER\"}, and must match exactly one row. Ask the user before deleting.",
     obj({"action": {"type": "string", "enum": ["read", "set", "click"], "default": "read"},
          "scope": {"type": "string", "description": "'command' (default), 'pane:<title>' or 'dialog:<index>'."},
          "grid": {"type": "string", "description": "Grid name if the panel has several."},
          "where": {"type": "object", "description": "read: only rows whose columns equal these values."},
          "row": {"description": "set/click: {column: value} identifying exactly one row, or a row index.", "type": ["object", "integer"]},
          "column": {"type": "string", "description": "Column name or header."},
          "value": {"description": "set: new value."}, "limit": {"type": "integer", "default": 200},
          "wait_seconds": {"type": "number", "default": 1.0}}),
     t_ui_grid, {"readOnlyHint": False, "destructiveHint": True}),
    ("command_ui_close", "Close the open command panel (all=true closes every open command).",
     obj({"all": {"type": "boolean", "default": False}}),
     lambda a: run_ipy("command_ui", "close", a), {"readOnlyHint": False, "destructiveHint": False}),
    ("tbc_dialogs", "List popups/message boxes TBC is showing (message text + buttons), click a button in one "
     "(e.g. 'Yes', 'No', 'OK'), fill fields in a dialog, or action=dismiss to back out safely (only presses "
     "Cancel/Close/No, otherwise closes with X; license popups are always closed with X). Never press buttons on "
     "license popups other than to back out - licensing is the user's business.",
     obj({"action": {"type": "string", "enum": ["list", "click", "fill", "dismiss", "file"], "default": "list",
                     "description": "file: type 'path' into a standard Open/Save dialog's File name box and press Open/Save."},
          "path": {"type": "string"},
          "force": {"type": "boolean", "default": False, "description": "Allow a non-cancel button on a license popup (only if the user asked)."},
          "index": {"type": "integer", "default": 0}, "button": {"type": "string"},
          "native": {"type": "boolean", "default": False, "description": "Target a standard Windows dialog (from list output)."},
          "values": FIELD_VALUES, "press": {"type": "string"}, "wait_seconds": {"type": "number", "default": 1.0}}),
     t_tbc_dialogs, {"readOnlyHint": False, "destructiveHint": True}),
    ("tbc_skills", "Knowledge base of documented TBC how-tos (*.skill.md). action=search looks across skills, saved "
     "scripts, lessons and remembered command panels - do this before starting a task. action=read returns a skill; "
     "action=save records a proven procedure (markdown body: when to use, steps or code, gotchas). Skills carry the "
     "TBC release(s) they were verified on (tbc_versions); a skill from another release cannot be overwritten: use "
     "action=append_version_section (name, body, optional release) to ADD a '## TBC <release>' section with what "
     "is different - the older release's text stays.",
     obj({"action": {"type": "string", "enum": ["list", "search", "read", "save", "append_version_section"], "default": "list"},
          "release": {"type": "string", "description": "append_version_section: TBC release (default: the running one)"},
          "query": {"type": "string"}, "kinds": {"type": "array", "items": {"type": "string", "enum": ["skill", "script", "lesson", "command"]}},
          "name": {"type": "string"}, "category": {"type": "string"}, "description": {"type": "string"},
          "body": {"type": "string"}, "requires_write": {"type": "boolean"}, "parameters": {"type": "array"},
          "overwrite": {"type": "boolean", "default": False}, "limit": {"type": "integer", "default": 15}}),
     t_skills, {"readOnlyHint": False, "destructiveHint": False}),
    ("tbc_script", "Saved, reusable IronPython scripts that run inside TBC with typed parameters (available to the "
     "script as the dict `args`; same globals as execute_python). mode='read' runs without a transaction, 'write' "
     "runs as one undo step that rolls back on error. Save a script once something works and is likely to be needed "
     "again; scripts are compile-checked on save. Destructive scripts should take a dry_run boolean defaulting to true.",
     obj({"action": {"type": "string", "enum": ["list", "read", "save", "run", "delete"], "default": "list"},
          "name": {"type": "string"}, "description": {"type": "string"},
          "mode": {"type": "string", "enum": ["read", "write"]},
          "parameters": {"type": "array", "items": obj({"name": {"type": "string"},
                                                       "type": {"type": "string", "enum": ["string", "number", "integer", "boolean", "array", "object"]},
                                                       "required": {"type": "boolean"}, "default": {}, "description": {"type": "string"}},
                                                      ["name", "type"])},
          "code": {"type": "string"}, "args": {"type": "object"}, "overwrite": {"type": "boolean", "default": False}}),
     t_script, {"readOnlyHint": False, "destructiveHint": True}),
    ("tbc_export", "Export data with TBC's own Export pane (Home > Export). action=formats lists the exporters per "
     "category (GIS, Construction, CAD, Custom, Points, Survey, Point Cloud, Mobile Mapping, Corridor). action=export: "
     "category + format (exporter name exactly as listed) + serials (objects to export) + path (FULL file path; never "
     "the project folder unless the user asks) [+ settings: [[field, value], ...] for exporter options]. Returns the "
     "file size. Never uses Remote Save (online). Examples: Custom 'P,N,E,elev,Code' (points CSV), CAD 'DXF exporter', "
     "Construction 'LandXML exporter'.",
     obj({"action": {"type": "string", "enum": ["formats", "export"], "default": "export"},
          "category": {"type": "string"}, "format": {"type": "string"},
          "serials": {"type": "array", "items": {"type": "integer"}}, "path": {"type": "string"},
          "settings": {"type": "array", "items": {"type": "array"}}, "overwrite": {"type": "boolean", "default": False},
          "wait_seconds": {"type": "number", "default": 3}}),
     t_export, {"readOnlyHint": False, "destructiveHint": False}),
    ("tbc_import", "Import files with TBC's own Import pane (Home > Import). action=scan: folder -> each file with the "
     "importer TBC detected (CHECK it, e.g. a P,N,E CSV can be detected as P,E,N). action=import: folder + files + "
     "confirm=true (ask the user first: importing changes the project and TBC COPIES each file into the project "
     "folder). Custom/CSV formats open TBC's Import Format Editor wizard; its Import button is pressed for you. Waits "
     "for Compute Project. Imported points go to the default Points layer.",
     obj({"action": {"type": "string", "enum": ["scan", "import"], "default": "scan"},
          "folder": {"type": "string"}, "files": {"type": "array", "items": {"type": "string"}},
          "confirm": {"type": "boolean", "default": False}, "wait_seconds": {"type": "number", "default": 3},
          "allow_cad": {"type": "boolean", "default": True, "description": "kept for compatibility; CAD import is allowed"}},
         ["folder"]),
     t_import, {"readOnlyHint": False, "destructiveHint": True}),
    ("tbc_wait_idle", "Wait until TBC has finished computing (Compute Project / progress windows gone and the project "
     "is not recalculating). The command tools already do this; call it after other changes before reading results.",
     obj({"timeout": {"type": "number", "default": 900}}),
     lambda a: {"idle_after_s": wait_idle(a.get("timeout"))}, {"readOnlyHint": True}),
    ("tbc_license", "What THIS user's TBC license allows (users have different licenses/subscriptions). "
     "action=summary: licensed features with expiry dates, subscription/maintenance dates, and how many commands are "
     "available - built automatically the first time a TBC session is seen and refreshed when the license changes. "
     "action=check keys=[...]: live check of specific commands. action=unlicensed (contains=...): commands not "
     "available. action=refresh: rebuild now. Commands are also checked live before every run.",
     obj({"action": {"type": "string", "enum": ["summary", "check", "unlicensed", "refresh"], "default": "summary"},
          "keys": {"type": "array", "items": {"type": "string"}}, "contains": {"type": "string"},
          "limit": {"type": "integer", "default": 200}}),
     t_license, {"readOnlyHint": True}),
    ("tbc_help", "TBC's own installed help (offline, ~3,500 topics). action=search finds topics by words; action=read "
     "returns a topic's text by topic number, or by command key (command='adjustprojectterranet') via the command's "
     "help topic. Read a command's help before using an unfamiliar command - it says what the command does, whether "
     "it acts immediately, and its options.",
     obj({"action": {"type": "string", "enum": ["search", "read"], "default": "search"},
          "query": {"type": "string"}, "topic": {"type": "string"}, "command": {"type": "string"},
          "limit": {"type": "integer", "default": 15}, "max_chars": {"type": "integer", "default": 6000}}),
     t_help, {"readOnlyHint": True}),
    ("tbc_preferences", "The user's standing rules (how they want things done in TBC). They are sent to every AI "
     "in this server's instructions, so they apply in every chat. action=add when the user states a lasting "
     "preference ('always...', 'from now on...', 'I want...'); update/remove when they change their mind; list to "
     "review. Use tbc_memory for facts about TBC, tbc_project_notes for one job's rules, this tool for the user's "
     "general wishes. The same preference is never stored twice. Ask before adding or changing.",
     obj({"action": {"type": "string", "enum": ["list", "add", "update", "remove"], "default": "list"},
          "text": {"type": "string"}, "topic": {"type": "string"}, "id": {"type": "integer"}}),
     t_preferences, {"readOnlyHint": False, "destructiveHint": False}),
    ("tbc_memory", "Lessons learned that persist across sessions. action=add after you discover something non-obvious "
     "(a field quirk, which command does X, a unit gotcha); pass command=<key> to attach it to a TBC command so it is "
     "shown next time that command is opened and when execute_python code names that command. action=search/list to "
     "recall; delete to remove a wrong lesson from the running release. Lessons must be GENERAL (useful on any job): no "
     "project names, point IDs, coordinates, dates, layer/surface names or site features - facts about the current job "
     "go in tbc_project_notes. The same lesson is never stored twice. Ask the user before adding.",
     obj({"action": {"type": "string", "enum": ["add", "search", "list", "delete"], "default": "list"},
          "text": {"type": "string"}, "topic": {"type": "string"}, "command": {"type": "string"},
          "tags": {"type": "array", "items": {"type": "string"}}, "query": {"type": "string"},
          "id": {"type": "integer"}, "limit": {"type": "integer", "default": 20}}),
     t_memory, {"readOnlyHint": False, "destructiveHint": False}),
    ("tbc_project_notes", "Notes about ONE job, in the project knowledge base SHARED with Civil 3D MCP and Project "
     "Analyzer (same files: what one tool learns about a job, the others see). For facts that only matter on this job: "
     "what its layers, point ranges, surfaces and codes are for, control and datum, which survey belongs to which "
     "feature, the client's standards, decisions the user made. A job is matched by folder: the open .vce belongs to "
     "the project whose linked folder contains it; its notes come back with project_info and the first code or panel "
     "result of a session. action=list (the open project's job, or project); link (project, optional folder; default "
     "the open .vce's folder) creates a job or adds a folder to one - link to an existing name when Civil 3D or the "
     "analyzer already know the job; unlink (project, folder); add (note) / update (id, note) / remove (id), optional "
     "project - only notes TBC wrote can be updated or removed, correct another tool's note by adding one; files lists "
     "the job's files folder (reference files the user drops in, and Project Analyzer's reports under analysis\\); read "
     "(file) returns a text file from it, e.g. analysis\\OVERVIEW.md. Notes are one line each, kept only on this "
     "computer. Ask the user before adding or changing.",
     obj({"action": {"type": "string", "enum": ["list", "link", "unlink", "add", "update", "remove", "files", "read"], "default": "list"},
          "project": {"type": "string", "description": "Job name; omit to use the job the open TBC project belongs to."},
          "folder": {"type": "string"}, "note": {"type": "string"},
          "id": {"type": "string", "description": "Note id, e.g. 'note-3'."},
          "file": {"type": "string", "description": "read: path inside the files folder, as listed by action=files."},
          "max_chars": {"type": "integer", "default": P.MAX_READ_CHARS}}),
     t_project_notes, {"readOnlyHint": False, "destructiveHint": False}),
]

if ALLOW_PYTHON:
    TOOLS.append((
        "execute_python",
        "Run IronPython 3.4 code inside TBC (full SDK access) - the escape hatch for anything the other tools don't cover. "
        "Predefined: project/prj (Trimble.Vce.Core.Components.Project), wv (WorldView), clr, TbcPoint, Point3D, Layer, "
        "Project, Model3D, GlobalSelection, TrimbleOffice, TransactMethodCall, Client, LinearType, jsonable, "
        "bridge (helpers: bridge.walk(wv), bridge.summarize(prj,o), bridge.lookup(prj,serial), bridge.factor(prj)). "
        "Coordinates are stored in meters; Point3D X=easting, Y=northing. print() output is returned; assign `result` "
        "to return data. By default runs in one undo-able transaction that rolls back on error. "
        "IronPython 3.4: avoid f-strings; use clr.GetClrType(T) for typeof.",
        obj({"code": {"type": "string"}, "transaction": {"type": "boolean", "default": True}}, ["code"]),
        t_execute_python,
        {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False}))

TOOL_MAP = {t[0]: t for t in TOOLS}

INSTRUCTIONS = (
    "Tools for Trimble Business Center (TBC) 2026. They talk to a bridge macro running inside TBC; if a call says the "
    "bridge is not running, ask the user to open TBC and click Macros > MCP Bridge. Coordinates default to the "
    "project's display units (see project_info). Object identity is the integer 'serial'. Every modifying call is one "
    "undo step in TBC.\n"
    "FIRST, once per session: tbc_skills action=read name=working_safely_in_tbc (all operating rules and the user's "
    "preferences in one place), and tbc_license action=summary (this user's license differs from others'; skills "
    "may describe commands this license lacks - search results flag them). Never suggest an unlicensed command as "
    "the way to do something; offer an alternative or tell the user which license feature it needs.\n"
    "Workflow: (1) tbc_skills action=search for the task first - reuse skills, saved scripts, lessons and remembered "
    "command panels. (2) Prefer the specific tools or a saved script. (3) For things only a TBC command can do: "
    "command_ui_open -> read the fields -> command_ui_fill (in the order a user would, then press the button) -> check "
    "'after' for popups (answer via tbc_dialogs) -> verify with read tools -> command_ui_close. (4) Use "
    "search_sdk_docs + execute_python for API-level work. (5) Afterwards, keep a knowledge base that grows (add, never "
    "delete), asking the user first: a standing rule from the user -> tbc_preferences add; a non-obvious gotcha -> "
    "tbc_memory add (with command=<key> for panel quirks); repeatable code -> tbc_script save; a proven procedure -> "
    "tbc_skills save. Ask the user before pressing buttons that commit large or irreversible changes.\n"
    "TWO SCOPES. Lessons, skills, scripts and panel notes are GENERAL TBC knowledge: never put project names, point "
    "IDs, coordinates, dates, layer/surface names or site features in them. Facts about the current job go in "
    "tbc_project_notes: a project knowledge base SHARED with Civil 3D MCP and Project Analyzer, matched to the job by "
    "the .vce's folder. When you start on a project, check its notes (project_info returns them; or tbc_project_notes "
    "action=list) and follow them; if Project Analyzer has analysed the job's documents, its reports are in the job's "
    "files folder under analysis\\ (tbc_project_notes action=files / read).\n"
    "'Here' / 'where I'm looking' = tbc_view action=info center. Leave TBC tidy: close every command panel and pane "
    "you opened (e.g. Layer Manager: run_command layermanager toggles it) and clear selections you made, unless the "
    "user wants to see them. Never press buttons on license popups except to back out (tbc_dialogs action=dismiss).\n"
    "TBC VERSIONS: the knowledge base was verified on TBC 2026.10 (build 44.0.9666); bridge_status reports the running "
    "release. Skills, lessons, command layouts and scripts carry the release they were verified on. If something no "
    "longer works on a newer release, ADD knowledge for that release (tbc_skills action=append_version_section, a new "
    "tbc_memory lesson, tbc_script save overwrite=true which archives the old version) - never delete or rewrite the "
    "older release's information."
)


# ---------------------------------------------------------------------------
# MCP JSON-RPC over stdio
# ---------------------------------------------------------------------------
def send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def result_text(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=1, ensure_ascii=False)


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}
    if mid is None:  # notification
        return None
    if method == "initialize":
        pv = params.get("protocolVersion")
        prefs = K.prefs_text()
        return {"protocolVersion": pv if pv in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": INSTRUCTIONS + ("\n\n" + prefs if prefs else "")}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": n, "description": d, "inputSchema": s, "annotations": ann}
                          for n, d, s, _, ann in TOOLS]}
    if method == "tools/call":
        name = params.get("name")
        t = TOOL_MAP.get(name)
        if t is None:
            raise RpcError(-32602, "Unknown tool: %s" % name)
        try:
            value = t[3](params.get("arguments") or {})
            img = value.pop("_image_path", None) if isinstance(value, dict) else None
            content = [{"type": "text", "text": result_text(value)}]
            if img:
                import base64
                with open(img, "rb") as f:
                    content.append({"type": "image", "mimeType": "image/png", "data": base64.b64encode(f.read()).decode("ascii")})
            return {"content": content, "isError": False}
        except (BridgeError, K.KnowledgeError) as ex:
            return {"content": [{"type": "text", "text": str(ex)}], "isError": True}
        except Exception as ex:
            return {"content": [{"type": "text", "text": "%s: %s" % (type(ex).__name__, ex)}], "isError": True}
    if method in ("resources/list", "prompts/list"):
        return {method.split("/")[0]: []}
    raise RpcError(-32601, "Method not found: %s" % method)


class RpcError(Exception):
    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code


def watch_tbc(poll=2.0):
    """Exit this MCP server once the TBC process it was bridging to has gone away (closed or crashed).
    Waits patiently until TBC has been seen at least once, so starting the server before TBC is fine."""
    import time
    seen_pid = None
    while True:
        time.sleep(poll)
        info = read_info()
        pid = info.get("pid") if info else None
        if pid and pid_alive(pid):
            seen_pid = pid
        elif seen_pid and not pid_alive(seen_pid):
            log("TBC (pid %s) has exited; shutting down MCP server." % seen_pid)
            if info and info.get("pid") == seen_pid:
                try:
                    os.remove(INFO_FILE)
                except OSError:
                    pass
            os._exit(0)


def main():
    if EXIT_WITH_TBC and not os.environ.get("TBC_MCP_PORT"):
        import threading
        threading.Thread(target=watch_tbc, name="tbc-watchdog", daemon=True).start()
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    except Exception:
        pass
    log("started; bridge info file:", INFO_FILE)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        try:
            res = handle(msg)
            if msg.get("id") is not None:
                send({"jsonrpc": "2.0", "id": msg["id"], "result": res})
        except RpcError as ex:
            send({"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": ex.code, "message": str(ex)}})
        except Exception as ex:
            send({"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": str(ex)}})


if __name__ == "__main__":
    main()
