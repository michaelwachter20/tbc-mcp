# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Trimble Business Center MCP server (stdio, no third-party dependencies).

Forwards MCP tool calls to the TbcMcpBridge macro running inside TBC and
offers an offline search over the TBC SDK XML documentation.

WHAT THIS FILE IS
  The process an AI client (Claude Code, Claude Desktop, any MCP client) starts and talks to. It is the only part
  of TBC MCP the AI sees: it publishes the tool list (TOOLS), the server instructions (INSTRUCTIONS) and runs every
  tool call. Python 3.12, standard library only (README: Python 3.15 failed inside its own html.parser).

ARCHITECTURE
  AI client
    -> MCP (JSON-RPC 2.0, one JSON object per line on stdin/stdout)                    -> this server
    -> TCP to 127.0.0.1:<port>, one JSON line per request carrying the session token   -> TbcMcpBridge macro
       (tbc_macro/TbcMcpBridge.py, IronPython 3.4 running inside TBC)
    -> TBC SDK calls, run on TBC's UI thread at Dispatcher "Background" priority       -> the open TBC project
  Socket request : {"id": n, "token": "...", "method": "<bridge h_<method>>", "params": {...}}
  Socket answer  : {"id": n, "ok": true, "result": ...}  or  {"id": n, "ok": false, "error": "...", "traceback": "..."}
  call_bridge() opens one short-lived TCP connection per request. The bridge's run_command is fire-and-forget
  (it answers {"queued": true} at once and runs the command later on the UI thread), every other method waits
  for its result.

  Most of the clever work runs INSIDE TBC as IronPython sent through the bridge's execute_python method:
    - run_ipy() sends a whole module from mcp_server/ipy/ (command_ui.py = the panel engine, view.py,
      license.py, import_export.py). They are read from disk on every call, so editing them needs no macro
      reinstall.
    - small inline snippets (the *_CODE constants in this file) for one-off lookups.
  Local knowledge lives in sibling modules: knowledge.py (K: skills, lessons, scripts, recorded panel layouts and
  preferences under knowledge/), projects.py (P: per-job notes shared with Civil 3D MCP and Project Analyzer),
  tbc_help.py (HELP: TBC's installed HTML help, read offline).

HOW THE BRIDGE IS FOUND
  When the user clicks Macros > MCP > 'MCP Bridge' in TBC, the macro binds a loopback port (47821, or one of the
  next 9 if that is taken), makes a fresh random token and writes {"port", "token", "pid", "version", "started"}
  to the info file %TEMP%\\tbc_mcp_bridge.json (TBC_MCP_INFO overrides the path). bridge_endpoint() reads that
  file on EVERY call, so a restarted bridge with a new port/token is picked up without restarting this server,
  and it checks that the recorded TBC pid is still alive. TBC_MCP_PORT + TBC_MCP_TOKEN bypass the file (and the
  watchdog) for a manually started bridge.

SECTIONS (in file order)
  1. configuration constants read from the environment, log()
  2. Bridge client: BridgeError, pid_alive, read_info, bridge_endpoint, call_bridge, run_ipy
  3. Command panel automation: the safety layer (license check, dialog classification, wait_idle, safe_dismiss,
     pace_command, danger confirms, native Windows dialogs, ui_after) and the handlers for run_command,
     list_commands, command_ui_*, tbc_view, ui_grid and tbc_dialogs
  4. Knowledge tools (tbc_skills, tbc_script), object handlers built on the bridge (delete_entities,
     get_entity, create_points) and TBC's installed help (tbc_help)
  5. Import / Export (Home tab): tbc_export, tbc_import
  6. License profile (tbc_license, license flags on knowledge), then running TBC release (tbc_version),
     bridge_status and tbc_preferences
  7. Project knowledge shared with Civil 3D MCP and Project Analyzer: active project path, project notes,
     project_info, execute_python, tbc_project_notes, tbc_memory
  8. SDK documentation search (offline, Macros SDK XML files)
  9. Tool definitions: TOOLS, TOOL_MAP, INSTRUCTIONS
 10. MCP JSON-RPC over stdio: send, handle, RpcError, watch_tbc (the watchdog), main

LIFE CYCLE
  main() starts the watchdog thread (unless TBC_MCP_EXIT_WITH_TBC=0 or TBC_MCP_PORT is set), then reads stdin
  line by line until the client closes it:
    initialize -> protocol version, capabilities, INSTRUCTIONS plus the user's standing preferences (K.prefs_text())
    tools/list -> TOOLS as MCP tool objects (name, description, inputSchema, annotations)
    tools/call -> TOOL_MAP[name][3](arguments). BridgeError / K.KnowledgeError become isError results carrying the
                  message text (written for the AI to read); any other exception also becomes an isError result
                  ("<ExceptionType>: <message>").
    ping, resources/list, prompts/list -> trivial answers; notifications (no id) are ignored.
  Nothing talks to TBC at startup: a missing bridge is reported per tool call, so the server may start before TBC.
  watch_tbc() polls the info file every 2 s; once it has seen a live TBC pid and that pid is gone, it removes the
  stale info file and ends the process (os._exit), so no orphaned server is left behind (tests/test_watchdog.py).

ADDING A TOOL
  1. Write a handler t_<name>(a) returning a JSON-able value (dict, list or str); `a` is the tool's arguments
     dict. Raise BridgeError (TBC side) or K.KnowledgeError (knowledge side) with a message meant for the AI.
     A dict result may carry "_image_path" (a PNG path) to attach an image (see t_view's screenshot).
  2. If the tool drives TBC's UI, reuse the safety helpers instead of raw calls: check_license,
     check_known_danger, wait_idle and pace_command before launching a command, ui_after after pressing a button,
     safe_dismiss for popups.
  3. Add a (name, description, obj({...}, required), handler, annotations) tuple to TOOLS. A plain bridge
     pass-through can be a lambda: call_bridge("<method>", a). A brand-new bridge method also needs an h_<method>
     in tbc_macro/TbcMcpBridge.py (installed into TBC by install_macro.ps1); new code in mcp_server/ipy/ does not.
  4. Add the tool to README > Tool catalog.

Environment variables (all optional):
  TBC_MCP_INFO      path of the bridge info file (default %TEMP%\\tbc_mcp_bridge.json)
  TBC_MCP_PORT      override port      (with TBC_MCP_TOKEN)
  TBC_MCP_TOKEN     override token
  TBC_MCP_TIMEOUT   seconds to wait for TBC to answer (default 120)
  TBC_SDK_DOCS      folder with the SDK *.xml docs (default C:\\Program Files (x86)\\Trimble\\Macros SDK)
  TBC_MCP_ALLOW_PYTHON  set to 0 to hide the execute_python tool
  TBC_MCP_EXIT_WITH_TBC set to 0 to keep running after TBC closes (default: exit when TBC exits/crashes)
  CIVIL3D_KNOWLEDGE_DIR shared project knowledge base (default Documents\\Civil3DMcp-KnowledgeBase, as Civil 3D MCP)
Also read further down in this file:
  TBC_MCP_IDLE_TIMEOUT  longest wait for Compute Project in wait_idle, seconds (default 900)
  TBC_MCP_COMMAND_GAP   minimum seconds between command launches in pace_command (default 2.5)
  TBC_MCP_USER_DIR      private per-user folder for license profiles (default %LOCALAPPDATA%\\TBC-MCP)
Read by the sibling modules: TBC_MCP_KNOWLEDGE_DIR (knowledge.py), TBC_HELP_DIR (tbc_help.py).
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

# The MCP client starts this file as a script (mcp_config_example.json: py -3.12 ...\tbc_mcp_server.py), not as a package, so
# put its own folder on sys.path to import the sibling modules knowledge.py, projects.py and tbc_help.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import knowledge as K  # noqa: E402
import projects as P  # noqa: E402
import tbc_help as HELP  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration (read once at startup; see the module docstring for the variables)
# ---------------------------------------------------------------------------
# IronPython helper modules sent into TBC by run_ipy() (command_ui.py, view.py, license.py, import_export.py)
IPY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ipy")

# Reported to the client in the initialize answer (serverInfo)
SERVER_NAME = "tbc-mcp"
SERVER_VERSION = "0.3.0"
# MCP protocol revisions this server answers with; the first is used when the client asks for one not listed
SUPPORTED_PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]

# Where the bridge macro publishes its port, token and TBC's pid (the macro writes Path.GetTempPath() +
# tbc_mcp_bridge.json, which is the same folder as tempfile.gettempdir() for the same Windows user)
INFO_FILE = os.environ.get("TBC_MCP_INFO") or os.path.join(tempfile.gettempdir(), "tbc_mcp_bridge.json")
# Default socket read timeout for a bridge answer, seconds. Long, because TBC can be slow or busy; a few
# callers pass shorter timeouts for quick checks.
TIMEOUT = float(os.environ.get("TBC_MCP_TIMEOUT", "120"))
# Macros SDK XML docs indexed by search_docs (README: they describe an older SDK than TBC 2026)
SDK_DOCS = os.environ.get("TBC_SDK_DOCS") or r"C:\Program Files (x86)\Trimble\Macros SDK"
# execute_python is only added to TOOLS when this is true (TBC_MCP_ALLOW_PYTHON=0 hides it)
ALLOW_PYTHON = os.environ.get("TBC_MCP_ALLOW_PYTHON", "1") != "0"
# Start the watch_tbc() watchdog thread in main() (TBC_MCP_EXIT_WITH_TBC=0 keeps the server alive after TBC exits)
EXIT_WITH_TBC = os.environ.get("TBC_MCP_EXIT_WITH_TBC", "1") != "0"


def log(*a):
    """Write a diagnostic line to stderr, prefixed with [tbc-mcp].

    stdout is reserved for MCP JSON-RPC messages (see send()), so anything human-readable must go to stderr,
    which MCP clients show in their server logs. flush=True so lines appear immediately.
    """
    print("[tbc-mcp]", *a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Bridge client
# ---------------------------------------------------------------------------
class BridgeError(Exception):
    """Any failure on the TBC side, with a message written for the AI (and user) to read.

    Raised for: bridge not running / not reachable / timed out, an error inside TBC (the bridge's error text plus
    its IronPython traceback), and every refusal of the safety layer (not licensed, CONFIRM NEEDED, popups already
    open, field-order guard, import-record delete, screenshot covered by another window ...). handle() turns it
    into an MCP result with isError=true and the message as text, so the AI can react instead of crashing.
    """
    pass


# Request ids for the bridge protocol; the bridge echoes them back (each call uses its own connection, so they
# only help when reading logs)
_ids = itertools.count(1)


def pid_alive(pid):
    """True if a process with this pid is running (Windows; falls back to True elsewhere).

    pid: int (or numeric string) from the bridge info file; falsy -> False.
    Used by bridge_endpoint() to spot an info file left behind by a crashed TBC, and by watch_tbc() to notice
    TBC exiting. Queries kernel32 directly through ctypes (standard library only).
    """
    if not pid:
        return False
    if os.name != "nt":
        return True
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        # No handle: either there is no such process, or it exists but we may not open it (e.g. it runs elevated)
        return ctypes.GetLastError() == 5  # access denied => exists
    try:
        code = ctypes.c_ulong()
        # A handle can still be opened for a process that has exited but whose handle is held elsewhere, so also
        # require the exit code to be STILL_ACTIVE
        return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def read_info():
    """The bridge info file as a dict ({"port", "token", "pid", "version", "started"}), or None.

    Never raises: a missing, half-written or unreadable file is simply None. utf-8-sig tolerates a BOM. Used where
    an absent bridge is normal (native_dialogs, view_covered_by_other_app and the watchdog only need TBC's pid);
    bridge_endpoint() reads the file itself because it must report WHY it could not connect.
    """
    try:
        with open(INFO_FILE, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


def bridge_endpoint():
    """(port, token) of the running bridge. Raises BridgeError with a user-facing hint when there is none.

    Order: TBC_MCP_PORT + TBC_MCP_TOKEN from the environment (manual connection, no pid check), else the info file.
    If the file names a pid that is no longer alive, TBC crashed or was killed without the macro's ProcessExit
    clean-up: the stale file is deleted and "TBC is not running" is raised (tests/test_watchdog.py checks this).
    Side effect: the token is registered with P.add_private so it can never be written into a shared project note.
    Called on every call_bridge(), so a bridge restarted with a new port/token is found without a server restart.
    """
    port, token = os.environ.get("TBC_MCP_PORT"), os.environ.get("TBC_MCP_TOKEN")
    if port and token:
        P.add_private(token, "the bridge's session token")
        return int(port), token
    try:
        with open(INFO_FILE, "r", encoding="utf-8-sig") as f:
            info = json.load(f)
        if info.get("pid") and not pid_alive(info["pid"]):
            # TBC crashed and left the file behind (a normal TBC exit or switching the bridge off deletes it)
            try:
                os.remove(INFO_FILE)
            except OSError:
                pass
            raise BridgeError("TBC is not running (it closed or crashed). Start TBC, open a project and click "
                              "Macros > MCP > 'MCP Bridge'.")
        P.add_private(info["token"], "the bridge's session token")  # never into shared project notes
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
    """Send one request to the bridge macro inside TBC and return its "result".

    method:  name of a bridge handler (h_<method> in tbc_macro/TbcMcpBridge.py), e.g. "ping", "project_info",
             "list_entities", "set_selection", "run_command", "execute_python".
    params:  dict passed to the handler (default {}).
    timeout: seconds to wait for the answer (default TIMEOUT = TBC_MCP_TIMEOUT, 120 s). The connect itself
             always gets a short 5 s (the bridge is on this machine's loopback address).
    Returns the handler's JSON-converted result (execute_python returns {"stdout": ..., "result": ...};
    run_command returns {"queued": true} immediately because the bridge runs commands fire-and-forget).
    Raises BridgeError: no bridge (see bridge_endpoint), connection refused, timeout (TBC busy or a modal
    dialog is blocking its UI thread), an empty answer, or ok=false (TBC's error plus the IronPython traceback).
    Every request carries the session token; the bridge rejects requests with a wrong one ("invalid token").
    Side effects: whatever the bridge method does in TBC. Inside TBC the work runs on the UI thread at
    Dispatcher Background priority, so this call waits until TBC's UI thread is free.
    """
    port, token = bridge_endpoint()
    req = {"id": next(_ids), "token": token, "method": method, "params": params or {}}
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.settimeout(timeout or TIMEOUT)
            # Protocol: exactly one JSON object per line in each direction (the bridge reads with ReadLine)
            s.sendall((json.dumps(req) + "\n").encode("utf-8"))
            buf = b""
            # Answers can be large (panel states, entity lists): read until the terminating newline
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
    except ConnectionRefusedError:
        # The info file was found (and its pid is alive) but nothing listens on that port any more
        raise BridgeError("TBC bridge not reachable on port %d. Is TBC open and the MCP Bridge macro started? "
                          "(It stops when TBC closes.)" % port)
    except socket.timeout:
        # NOTE: tbc_busy() recognises this message by its "Timed out" prefix and treats it as "TBC is busy"
        raise BridgeError("Timed out waiting for TBC (it may be busy or showing a dialog).")
    if not buf:
        raise BridgeError("Bridge closed the connection without answering.")
    # A malformed answer raises ValueError here (not BridgeError); handle() still reports it as an isError result
    resp = json.loads(buf.decode("utf-8-sig"))
    if not resp.get("ok"):
        # Errors raised inside TBC come back with the IronPython traceback: pass it on, the AI needs it to fix
        # its execute_python code
        msg = resp.get("error", "unknown error")
        if resp.get("traceback"):
            msg += "\n\nTraceback (inside TBC):\n" + resp["traceback"]
        raise BridgeError(msg)
    return resp.get("result")


def run_ipy(module, action, args, transaction=False):
    """Run one of the IronPython helper modules in mcp_server/ipy inside TBC.
    Loaded fresh on every call, so editing them needs no macro reinstall.

    module:      file name without .py in mcp_server/ipy: "command_ui" (panel engine: state, fill, click, close,
                 license, close_dialog, grid_*), "view" (info, screenshot, set_extents, screen_rect), "license"
                 (fingerprint, profile) or "import_export" (import_*, export_*).
    action:      name of the function in that module's dispatch table (its last line maps ACTION -> function).
    args:        dict handed to that function as ARGS (JSON round-trip, so only JSON-able values).
    transaction: passed on to execute_python. False (default) runs the module outside an MCP undo transaction;
                 every caller in this file uses the default.
    Returns the module's `result` (the value of `result` inside execute_python's answer).
    Raises BridgeError like call_bridge (errors inside the module come back with their IronPython traceback).
    How it works: prepends `ACTION = '<action>'` and `ARGS = json.loads('<args>')` to the module's source and
    sends the whole text through the bridge's execute_python, which runs it with the bridge's globals (prj,
    TrimbleOffice, bridge, ...). ARGS travels as a JSON string inside a Python string literal (%r) and is parsed
    again inside TBC, so nested dicts and lists arrive intact. Every call re-reads the file from disk.
    """
    with open(os.path.join(IPY_DIR, module + ".py"), "r", encoding="utf-8-sig") as f:  # tolerate a BOM
        src = f.read()
    code = "ACTION = %r\nimport json as _j\nARGS = _j.loads(%r)\n" % (action, json.dumps(args or {})) + src
    return call_bridge("execute_python", {"code": code, "transaction": transaction}).get("result")


# ---------------------------------------------------------------------------
# Command panel automation
# ---------------------------------------------------------------------------
# This section is the safety layer between the AI and TBC's user interface (README > Built-in safety and the
# working_safely_in_tbc skill): license check before a command opens, refusal of commands recorded as dangerous,
# pacing between command launches, waiting while TBC computes, careful popup handling, and the handlers of the
# panel tools (run_command, command_ui_*, ui_grid, tbc_dialogs, tbc_view).
#
# Dialog dicts used throughout (built by dialogs_snapshot / native_dialogs):
#   TBC dialog (WinForms or WPF): {"index": n, "title", "message", "fields", "buttons": [text or id, ...]}
#   standard Windows dialog:      {"native": True, "hwnd", "title", "message", "buttons"}

# The only buttons ever pressed automatically: they back out of a popup (README: "Only Cancel, Close or No are
# ever pressed automatically"). Compared lower-cased against the button text.
SAFE_BUTTONS = ("cancel", "close", "no", "abort")
# Substrings of a popup's title + message that mark it as a license/subscription popup ("licens" matches license,
# licensed, licensing). Licensing is the user's business: such popups are only ever closed with X.
LICENSE_WORDS = ("licens", "subscription", "entitlement", "not authorized", "unauthorized")


def is_license_dialog(d):
    """True if dialog dict d looks like a TBC license / subscription popup (LICENSE_WORDS in title or message).

    Callers never press a button other than X on such a popup (safe_dismiss, ui_after, t_command_ui_open), and
    t_tbc_dialogs refuses a non-backing-out button while one is open unless force=true.
    """
    t = ("%s %s" % (d.get("title") or "", d.get("message") or "")).lower()
    return any(w in t for w in LICENSE_WORDS)


def check_license(key):
    """Silent license check; raises BridgeError instead of letting TBC open its license popups.

    key: TBC command key (e.g. "addpoint", "delete"); the lookup inside TBC is case-insensitive.
    Asks command_ui.license inside TBC, which compares the command's LicenseCodes with Server.CanUseFeature
    without running the command, so TBC never gets the chance to show its license popup.
    Returns {"exists": True, "licensed": True/None, "needs_any_of": [feature codes]} (licensed None = TBC's
    check itself failed: allowed through). Raises BridgeError "No TBC command" for an unknown key and
    "NOT LICENSED" for a command this license lacks.
    Called before every command launch: t_run_command, t_command_ui_open, t_delete_entities.
    """
    r = run_ipy("command_ui", "license", {"keys": [key]}).get(key, {})
    if r.get("exists") is False:
        raise BridgeError("No TBC command with key '%s' (see list_commands)." % key)
    if r.get("licensed") is False:
        raise BridgeError("NOT LICENSED: '%s' needs one of %s, which this TBC license doesn't include. "
                          "Skipped without opening it." % (key, r.get("needs_any_of")))
    return r


# Substrings of a popup's title + message that mark a TBC progress window ("comput" matches Compute Project /
# Computing the project, "recalculat" matches recalculate / recalculating)
BUSY_WORDS = ("comput", "processing", "progress", "please wait", "loading", "calculating", "recalculat")
# TBC error popups are appended here (knowledge/memory/tbc_errors.log; git-ignored, see .gitignore) so they can be
# investigated later. K.ROOT follows TBC_MCP_KNOWLEDGE_DIR.
ERROR_LOG = os.path.join(K.ROOT, "memory", "tbc_errors.log")


def is_busy_dialog(d):
    """TBC progress windows (e.g. 'Compute Project' / 'Computing the project' with only a Cancel button).
    These must never be dismissed - pressing Cancel aborts the computation.

    d: dialog dict. True when BUSY_WORDS appear in title + message AND the window has no buttons or only Cancel
    (so an ordinary question that merely mentions "processing" next to Yes/No is not mistaken for one).
    Used by tbc_busy (to wait), safe_dismiss and t_import (to leave such windows alone).
    """
    t = ("%s %s" % (d.get("title") or "", d.get("message") or "")).lower()
    btns = [b.lower() for b in d.get("buttons") or [] if b]
    return any(w in t for w in BUSY_WORDS) and (not btns or btns == ["cancel"])


def is_error_dialog(d):
    """True if dialog dict d looks like a TBC error report / crash popup.

    Signs: "<<" or ">>" buttons (TBC's error-report window has them; the working_safely_in_tbc skill:
    "TBC error-report popups (buttons << / OK)"), exception wording ("exception",
    "unexpected error", "has stopped", .NET's "object reference not set ..."), or a window titled exactly "Error".
    Such popups are logged with log_tbc_error; ui_after then tells the AI to stop and tell the user.
    """
    t = ("%s %s" % (d.get("title") or "", d.get("message") or "")).lower()
    btns = [b.lower() for b in d.get("buttons") or [] if b]
    return ("<<" in btns or ">>" in btns or "exception" in t or "unexpected error" in t or "has stopped" in t
            or "object reference not set" in t or (d.get("title") or "").strip().lower() == "error")


def log_tbc_error(d, context=""):
    """Append a TBC error popup (title + message) to ERROR_LOG with a timestamp.

    d: dialog dict; context: short tag saying where it was seen ("safe_dismiss", "after button press",
    "tbc_import"). Side effect: creates the memory folder if needed and writes to the local log file. TBC is not
    touched.
    """
    os.makedirs(os.path.dirname(ERROR_LOG), exist_ok=True)
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write("%s  [%s] %s\n%s\n\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), context, d.get("title"), d.get("message")))


def tbc_busy():
    """True while TBC is computing (project calculate loop or a progress window is up).

    Two checks, in this order: any progress window among the open popups (is_busy_dialog), then the project's
    InCalculateLoop flag read through execute_python. A bridge timeout also counts as busy, because the bridge
    can only answer when TBC's UI thread is free. Other BridgeErrors (e.g. bridge not running) propagate.
    Read-only: several small bridge calls, nothing is changed in TBC.
    """
    try:
        st = ui_state(include_text=False)
        if any(is_busy_dialog(x) for x in dialogs_snapshot(st)):
            return True
        # 60 s instead of the 120 s default: a slower answer is treated as "busy" and asked again by wait_idle
        return bool(call_bridge("execute_python", {"code": "result = bool(prj.InCalculateLoop) if prj is not None else False",
                                                   "transaction": False}, timeout=60).get("result"))
    except BridgeError as ex:
        if "Timed out" in str(ex):  # the message call_bridge raises on socket.timeout
            return True  # UI thread busy
        raise


def wait_idle(timeout=None, settle=1.5):
    """Block until TBC has finished computing (user preference: wait for Compute Project before anything else).

    timeout: longest total wait in seconds (default TBC_MCP_IDLE_TIMEOUT, 900 s = 15 min; 0/None = default).
    settle:  once TBC HAS been busy during this call, it must stay idle this long (1.5 s) before returning, so a
             computation that starts again right after a progress window closes is not missed. If TBC was idle
             from the first check, the call returns at once.
    Returns the seconds spent (rounded to 0.1); 0.0 means TBC was already idle, and callers use a truthy value
    to report "waited_for_compute_s".
    Raises BridgeError when TBC is still busy after `timeout` (the user decides whether to wait longer), or any
    BridgeError from tbc_busy (e.g. bridge not running).
    Never presses anything: progress windows are waited out, never cancelled (working_safely_in_tbc rule 4).
    Called before every command action and after every button press (via ui_after); also the tbc_wait_idle tool.
    """
    timeout = float(timeout or os.environ.get("TBC_MCP_IDLE_TIMEOUT", "900"))
    t0 = time.time()
    idle_since = None
    waited = False
    while time.time() - t0 < timeout:
        if tbc_busy():
            waited = True
            idle_since = None
            time.sleep(1.0)  # poll once a second while busy; each check is several bridge calls on TBC's UI thread
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
    (we wait for them instead). Error reports are logged before closing. Single pass, never loops.

    dialogs: list of dialog dicts to handle. None = wait_idle() first, then every popup currently open
             (dialogs_snapshot). Callers that already have a list (ui_after, t_command_ui_open, t_create_points)
             pass just the popups they want gone.
    Returns a list of action dicts, one per dialog ({"dialog": title, "action": "pressed Cancel" | "closed with X"
    | "left alone ..." | "failed: ...", "license": bool}), plus a final {"still_open": [...], "note": ...} entry
    when popups remain after one pass.
    Side effects: presses a safe button or closes windows in TBC (WinForms/WPF via command_ui, standard Windows
    dialogs via native_dialogs), writes error popups to ERROR_LOG, sleeps 1 s before re-checking.
    One pass only: whatever is still open afterwards is reported for the user to close, never retried.
    """
    if dialogs is None:
        wait_idle()
        dialogs = dialogs_snapshot()
    actions = []
    for d in dialogs:
        if is_busy_dialog(d):
            # Pressing Cancel on a progress window would abort TBC's computation
            actions.append({"dialog": d.get("title"), "action": "left alone (TBC is computing)"})
            continue
        if is_error_dialog(d):
            # Log first (the text is gone once the window closes); the dialog is then closed like any other below
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
                # No backing-out button, or a license popup (always X, whatever buttons it has): close the window
                # as its title-bar X would (WM_CLOSE / Form.Close), pressing nothing
                if d.get("native"):
                    native_dialogs(close_hwnd=d["hwnd"])
                else:
                    run_ipy("command_ui", "close_dialog", {"index": d["index"]})
                actions.append({"dialog": d.get("title"), "action": "closed with X", "license": lic})
        except BridgeError as ex:
            actions.append({"dialog": d.get("title"), "action": "failed: %s" % ex})
    if actions:
        # Buttons are pressed and windows closed asynchronously inside TBC: give them a second, then look again
        time.sleep(1.0)
        left = [x for x in dialogs_snapshot() if not is_busy_dialog(x)]
        if left:
            actions.append({"still_open": [x.get("title") for x in left],
                            "note": "Stopped after one pass; ask the user to close these."})
    return actions


# Minimum seconds between two command launches (README "Paced launches": at least 2.5 s). TBC_MCP_COMMAND_GAP.
COMMAND_GAP = float(os.environ.get("TBC_MCP_COMMAND_GAP", "2.5"))
# Time of the last command launch; a one-element list so pace_command can update it without `global`
_last_command = [0.0]


def pace_command():
    """TBC is slow to open commands: keep a minimum gap between command launches (user preference).

    Sleeps until COMMAND_GAP seconds have passed since the previous launch from this server, then records now.
    Call it right before call_bridge("run_command", ...). Only paces launches from this server process.
    """
    wait = _last_command[0] + COMMAND_GAP - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_command[0] = time.time()


# Phrases in a lesson about a command that make opening that command need confirm=true. They match the wording
# used in recorded lessons (README "Ask before acting": commands that act immediately or open a web page).
# tbc_memory add warns when a new lesson contains one of these, because it changes how the command behaves.
DANGER_WORDS = ("acts immediately", "opens a trimble web page", "opens the gnss loop closure report", "crashed tbc")


def check_known_danger(key, confirm):
    """Refuse commands the knowledge base marks as acting immediately / opening the browser, unless confirmed.

    key: TBC command key; confirm: the tool's confirm argument (truthy = the user agreed).
    Looks at lessons whose topic is this command key (K.list_lessons(key.lower())) for DANGER_WORDS. Raises
    BridgeError "CONFIRM NEEDED: ..." quoting those lessons so the AI asks the user and calls again with
    confirm=true. Returns None when there is nothing to confirm. Local only: TBC is not touched.
    """
    hits = [l["text"] for l in K.list_lessons(key.lower()) if any(w in l["text"].lower() for w in DANGER_WORDS)]
    if hits and not confirm:
        raise BridgeError("CONFIRM NEEDED: '%s' is recorded as: %s  Ask the user, then call again with confirm=true."
                          % (key, " / ".join(hits)))


def t_run_command(a):
    """Tool run_command: launch a TBC command by key, as the user would from the ribbon.

    a: {"key": str, "args": list (passed to TBC's ExecuteCommand), "confirm": bool}.
    Safety order: license check (no license popup), danger confirm, wait until TBC is idle, pace launches.
    Returns the bridge's {"queued": true}: the bridge starts the command asynchronously on TBC's UI thread
    (a command may open a modal dialog that would otherwise block the bridge), so this does NOT wait for the
    command to open or finish. Use command_ui_open when the panel is needed.
    """
    check_license(a["key"])
    check_known_danger(a["key"], a.get("confirm"))
    wait_idle()
    pace_command()
    return call_bridge("run_command", {"key": a["key"], "args": a.get("args") or []})


def t_list_commands(a):
    """Tool list_commands: TBC's command list ({"count", "commands": [{"key", "caption", "licensed"}]}).

    a: {"contains": substring of key or caption, "limit": int (default 300)} - passed straight to the bridge.
    Each returned command gets "licensed" (True / False / None) from one live command_ui.license call for all
    returned keys, so the AI can avoid suggesting commands this license lacks. Read-only.
    """
    r = call_bridge("list_commands", a)
    lic = run_ipy("command_ui", "license", {"keys": [c["key"] for c in r.get("commands", [])]})
    for c in r.get("commands", []):
        l = lic.get(c["key"], {})
        c["licensed"] = l.get("licensed")
    return r


def native_dialogs(click=None, close_hwnd=None, set_file=None):
    """Standard Windows dialogs (#32770, e.g. MessageBox / file pickers) owned by TBC. Optionally click a button
    or close one (WM_CLOSE, like its X).

    These are not WinForms/WPF windows, so command_ui (which runs inside TBC) does not see them; they are found
    from OUTSIDE TBC with the Win32 API: every visible top-level window of class "#32770" whose process is the
    TBC pid from the bridge info file. No bridge call is involved: this runs entirely in the server process.

    Exactly one mode per call (checked in this order):
      set_file=path   type the path into the first open Open/Save dialog's "File name" box and press Open/Save.
                      Returns {"file_set", "pressed", "dialog"}; BridgeError if no such dialog or button.
      close_hwnd=h    post WM_CLOSE to that window (like its X). Returns {"closed": h}.
      click=text      press the first button with that text (case-insensitive, "&" accelerators removed) in any
                      native dialog. Returns {"clicked", "dialog"}; BridgeError listing the open dialogs if none.
      (none)          list them: [{"native": True, "hwnd", "title", "message" (static texts, max 1500 chars),
                      "buttons": [texts]}].
    Returns [] when not on Windows or when the info file has no pid (no bridge).
    Messages are POSTED (PostMessageW), so the call returns before the dialog has reacted.
    """
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
        """Window caption / control text of window handle h."""
        n = u.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, b, n + 1)
        return b.value

    def cls(h):
        """Win32 window class name of h ("#32770" = standard dialog box, "Button", "Static", "Edit", ...)."""
        b = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(h, b, 256)
        return b.value

    out = []
    # Signature of EnumWindows / EnumChildWindows callbacks: BOOL CALLBACK(HWND, LPARAM); returning True continues
    proto = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

    def top(h, _):
        """EnumWindows callback: collect h into `out` if it is a visible standard dialog of TBC's process."""
        p = W.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        # Only TBC's own visible standard dialogs; never another application's windows
        if p.value == pid and u.IsWindowVisible(h) and cls(h) == "#32770":
            statics, buttons = [], []

            def kid(k, _2):
                """EnumChildWindows callback: Buttons become the dialog's buttons; Static controls hold a
                MessageBox's text."""
                c = cls(k)
                t = txt(k)
                if c == "Button" and t:
                    buttons.append((k, t.replace("&", "")))  # "&Yes" -> "Yes" (& marks the keyboard accelerator)
                elif c == "Static" and t:
                    statics.append(t)
                return True
            u.EnumChildWindows(h, proto(kid), 0)
            # "_buttons" keeps the (hwnd, text) pairs for clicking; it is removed before the list is returned
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
                """EnumChildWindows callback collecting the File name box: a visible Edit whose parent is a
                ComboBox / ComboBoxEx32, or whose grandparent is a ComboBoxEx32."""
                if cls(k) == "Edit" and u.IsWindowVisible(k):
                    par = u.GetParent(k)
                    if cls(par) in ("ComboBox", "ComboBoxEx32") or cls(u.GetParent(par)) == "ComboBoxEx32":
                        edits.append(k)
                return True
            u.EnumChildWindows(d["hwnd"], proto(kid2), 0)
            if not edits:
                continue  # not a file dialog (e.g. a MessageBox): try the next native dialog
            # Declare the argument types so the path is passed as a wide-string pointer (lParam of WM_SETTEXT).
            # Note: this sets argtypes on the shared user32.SendMessageW for the rest of the process.
            u.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, ctypes.c_wchar_p]
            # SendMessage (synchronous) so the text is in the box before the button is clicked
            u.SendMessageW(edits[0], 0x000C, 0, set_file)  # WM_SETTEXT
            for hb, t in d["_buttons"]:
                if t.lower() in ("open", "save", "&open", "&save"):
                    u.PostMessageW(hb, 0x00F5, 0, 0)  # BM_CLICK
                    return {"file_set": set_file, "pressed": t, "dialog": d["title"]}
            raise BridgeError("File dialog '%s' has no Open/Save button: %s" % (d["title"], d["buttons"]))
        raise BridgeError("No standard file dialog is open")
    if close_hwnd:
        # WM_CLOSE is what the title-bar X sends: the dialog closes without any of its buttons being pressed.
        # (close_hwnd is not checked against the list above; callers pass an hwnd taken from it.)
        u.PostMessageW(close_hwnd, 0x0010, 0, 0)  # WM_CLOSE
        return {"closed": close_hwnd}
    if click:
        # First matching button text in any of TBC's native dialogs (in EnumWindows order)
        for d in out:
            for hb, t in d["_buttons"]:
                if t.lower() == click.lower():
                    u.PostMessageW(hb, 0x00F5, 0, 0)  # BM_CLICK
                    return {"clicked": t, "dialog": d["title"]}
        raise BridgeError("No native dialog button '%s'. Open: %s" % (click, [(d["title"], d["buttons"]) for d in out]))
    for d in out:
        d.pop("_buttons")  # window handles of the buttons are internal: not JSON-friendly, not useful to the AI
    return out


def ui_state(scope=None, include_hidden=False, include_text=True):
    """Snapshot of TBC's UI from the panel engine (command_ui.state inside TBC). Read-only.

    scope:          None/"command" = the open command panel, "dialog:<index>" = a TBC popup,
                    "pane:<title>" = a docked pane such as "pane:Layer Manager".
    include_hidden: also list fields in collapsed / hidden sections.
    include_text:   also return the panel's free texts (labels that are not field labels), max 80.
    Returns a dict that always has "modal_dialogs" ([{"index", "title", "type"}]), "open_command" (key or None)
    and "panes"; when the scope exists also "command" / "dialog" / "pane", "fields" (label, id, kind, value,
    options, status ...), "buttons", "tabs" and, for panes, "grids". With scope "command" and no command open,
    only the first three keys are present.
    """
    return run_ipy("command_ui", "state", {"scope": scope, "include_hidden": include_hidden, "include_text": include_text})


def dialogs_snapshot(st=None):
    """Every popup TBC is showing right now, as dialog dicts: TBC's own (WinForms modal forms and visible WPF
    windows, via command_ui) followed by standard Windows dialogs (native_dialogs).

    st: a ui_state() result to reuse (saves one bridge call); None = take a fresh one.
    For each TBC popup a second ui_state("dialog:<i>") call reads its content: "message" = the text fields'
    values plus the free texts (max 1500 chars), "fields" (without the MessageRichTextBox that holds the
    message itself) and "buttons". If reading a popup fails, its bare {"index", "title", "type"} entry is used.
    Read-only; costs 1 + (number of TBC popups) bridge calls.
    """
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
    """What happened after pressing a button: open command, popups, field status messages.

    wait: seconds to sleep first, giving TBC time to react to the (asynchronous) press; the tools' wait_seconds.
    Then waits for any recomputation (wait_idle) and inspects the UI. Returns a dict:
      "open_command"          key of the command panel still open (or None)
      "waited_for_compute_s"  only when wait_idle actually had to wait
      "tbc_error" + "hint"    TBC error popups (logged to ERROR_LOG); returned at once, nothing else is done -
                              the hint tells the AI to stop and tell the user
      "license_problem" + "auto_dismissed"  license popups, closed right away with X via safe_dismiss
      "dialogs" + "hint"      any other popup, left open for the AI to read and answer with tbc_dialogs
      "field_status"          the StatusMessage of fields in the open panel that have one (TBC's field messages)
    Side effects: may close license popups; writes error popups to ERROR_LOG.
    Used after every button press: command_ui_fill (with press), command_ui_click, ui_grid set/click,
    tbc_dialogs click/file.
    """
    time.sleep(wait)
    waited = wait_idle()  # TBC may now recompute the project: never act while it does
    st = ui_state(include_text=False)
    snap = {"open_command": st.get("open_command")}
    if waited:
        snap["waited_for_compute_s"] = waited
    d = dialogs_snapshot(st)
    errs = [x for x in d if is_error_dialog(x)]
    if errs:
        # An error report wins over everything else: log it and leave it on screen for the user (not dismissed)
        for x in errs:
            log_tbc_error(x, "after button press")
        snap["tbc_error"] = [{"title": x.get("title"), "message": x.get("message")} for x in errs]
        snap["hint"] = "TBC reported an error (logged). Stop and tell the user before doing anything else."
        return snap
    lic = [x for x in d if is_license_dialog(x)]
    if lic:
        # License popups are backed out of at once (closed with X by safe_dismiss), never answered
        snap["license_problem"] = [{"title": x.get("title"), "message": x.get("message")} for x in lic]
        snap["auto_dismissed"] = safe_dismiss(lic)
        d = [x for x in d if not is_license_dialog(x)]
    if d:
        # Any other popup is left open for the AI to read and answer (tbc_dialogs), not auto-dismissed
        snap["dialogs"] = d
        snap["hint"] = "A popup is waiting. Read it and answer with tbc_dialogs action=click (or action=dismiss)."
    stat = [{"field": f.get("label") or f.get("id"), "status": f["status"]} for f in st.get("fields", []) if f.get("status")]
    if stat:
        snap["field_status"] = stat
    return snap


def t_command_ui_open(a):
    """Tool command_ui_open: start a TBC command and return its panel once it has finished building.

    a: {"key": command key, "wait_seconds": total wait for the panel (default 15), "settle_seconds": how long
        the field list must stay unchanged (default 1.2; not in the tool schema, used internally),
        "include_hidden": bool, "confirm": bool}.
    Steps: license check -> danger confirm -> wait_idle -> refuse if popups are already open (they must be
    dealt with first, via tbc_dialogs) -> pace_command -> run_command (asynchronous in TBC) ->
    poll once a second until a panel or popup appears -> wait until the fields stop changing -> full state.
    Returns the ui_state of the panel plus: "dialogs" (popups that appeared), "remembered" (notes and lessons
    recorded for this command), "project_notes" (first time per project), "note" when nothing appeared, or
    {"not_licensed": True, "license_problem", "auto_dismissed"} if TBC still showed a license popup.
    Side effects: opens a command in TBC (left open for command_ui_fill / _close); records the panel layout to
    knowledge/commands/<key>.json (K.record_command); on a license popup closes it and every open command.
    Also used internally by t_create_points, t_export and t_import.
    """
    key = a["key"]
    check_license(key)
    check_known_danger(key, a.get("confirm"))
    wait_idle()
    pre = dialogs_snapshot()
    if pre:
        raise BridgeError("Popups are already open in TBC; deal with them first (tbc_dialogs): %s"
                          % [(x.get("title"), x.get("buttons")) for x in pre])
    # Remember which command was open before, to tell "the new panel is up" from "the old one is still there"
    before = ui_state(include_text=False).get("open_command")
    pace_command()
    call_bridge("run_command", {"key": key})  # returns at once ({"queued": true}); the panel opens later
    deadline = time.time() + float(a.get("wait_seconds", 15))
    st = None
    # Phase 1: wait for something to appear - a popup, or an open command that is this key or differs from before
    while time.time() < deadline:
        time.sleep(1.0)  # gentle polling: don't keep interrupting TBC while it builds the panel
        st = ui_state(include_text=False)
        oc = st.get("open_command")
        if st.get("modal_dialogs") or (oc and (oc.lower() == key.lower() or oc != before)):
            break
    # TBC builds panels gradually: wait until the field list stops changing before anyone fills it
    # Phase 2 (shares phase 1's deadline): the (id, value) list of all fields must stay the same for settle_seconds
    sig, stable_since = None, time.time()
    while time.time() < deadline:
        cur = ui_state(include_text=False)
        # Signature of the panel: every field's id and value. It changes while TBC is still adding fields or
        # filling in defaults.
        s = json.dumps([(f.get("id"), f.get("value")) for f in cur.get("fields", [])], default=str)
        if s != sig:
            sig, stable_since = s, time.time()
        elif time.time() - stable_since >= float(a.get("settle_seconds", 1.2)):
            break
        if cur.get("modal_dialogs"):
            break  # a popup appeared: stop waiting, it is reported below
        time.sleep(0.8)
    # Final, full read (with free texts and, if asked, hidden fields) of the panel the AI will work with
    st = ui_state(include_hidden=bool(a.get("include_hidden")))
    ds = dialogs_snapshot(st)
    lic = [x for x in ds if is_license_dialog(x)]
    if lic:
        # licensed by feature code but TBC still refused: back out, never click into the license manager
        st = {"not_licensed": True, "command": None, "license_problem": [{"title": x.get("title"), "message": x.get("message")} for x in lic],
              "auto_dismissed": safe_dismiss(lic)}
        try:
            run_ipy("command_ui", "close", {"all": True})  # close whatever got opened, so TBC is left tidy
        except BridgeError:
            pass
        return st
    if ds:
        st["dialogs"] = ds
    if st.get("command"):
        # Learn the panel layout (knowledge/commands/<key>.json) and hand back what earlier sessions noted
        K.record_command(st)
        mem = K.remembered_for_command(st["command"]["key"])
        if mem:
            st["remembered"] = mem
    elif not st.get("modal_dialogs"):
        st["note"] = ("No panel or dialog appeared. The command may act immediately (check with read tools), "
                      "may need a selection first, or may use a different key (see list_commands).")
    return with_project_notes(st)


def t_command_ui_inspect(a):
    """Tool command_ui_inspect: re-read the open command panel, a popup or a docked pane. Read-only in TBC.

    a: {"scope": None/"command" | "dialog:<index>" | "pane:<title>", "include_hidden": bool,
        "include_text": bool (default True)}.
    Returns ui_state(...) plus "dialogs" (full dialogs_snapshot) when popups are open. For the command panel
    (no scope given) it also records the layout (K.record_command, a local knowledge write) and adds
    "remembered" notes, like command_ui_open.
    """
    st = ui_state(a.get("scope"), bool(a.get("include_hidden")), a.get("include_text", True))
    if st.get("modal_dialogs"):
        st["dialogs"] = dialogs_snapshot(st)
    if st.get("command") and not a.get("scope"):
        K.record_command(st)
        mem = K.remembered_for_command(st["command"]["key"])
        if mem:
            st["remembered"] = mem
    return st


# Pause after every fill (and after choosing an exporter / import files): README "Settle time" - lets TBC finish
# drawing previews before the next step. Seconds.
FILL_SETTLE_S = 0.8

# Field orders TBC cannot handle: (command key, fields that need `required` to be filled first, required field)
# The trigger fields are matched lower-cased against the label/id given by the caller; the required field by its
# exact on-screen label. Add an entry here when another panel turns out to need a field before another.
FILL_ORDER_GUARDS = [
    ("DivideArea", ("origin", "end point"), "Area to Divide"),  # TBC crashed when Origin was typed with no area set
]


def guard_fill(pairs):
    """Refuse a fill that would type a guarded field before its prerequisite (FILL_ORDER_GUARDS).

    pairs: [[label_or_id, value], ...] about to be filled into the open command panel.
    Passes when the open command is not guarded, no trigger field is being filled, the required field is part of
    the same fill (by exact label), or it already has a value in the panel. Otherwise raises BridgeError.
    Note: when the required field is in the same fill, its position in the list is not checked.
    Read-only: one ui_state call.
    """
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
    """Tool command_ui_fill (also used by tbc_dialogs fill, create_points and tbc_export): fill fields like a user.

    a: {"values": {label_or_id: value} or [[label_or_id, value], ...] (in order), "press": button to press
        afterwards, "scope": None | "dialog:<i>" | "pane:<title>", "stop_on_error": bool (default True),
        "wait_seconds": pause before inspecting after the press (default 1.0)}.
    Steps: wait_idle -> guard_fill -> command_ui.fill inside TBC (types each value and tabs out so TBC validates
    it; re-reads every field afterwards because a later entry can reset an earlier one) -> FILL_SETTLE_S pause ->
    if a button was pressed, ui_after.
    Returns {"set": [{"field", "label", "requested", "now", "status", "warning"?}], "errors": [...],
    "pressed"?: button text, "after"?: ui_after result}. The button is only pressed when no field failed.
    Changes TBC: fields are typed into and the pressed button acts (e.g. Add, Apply, OK).
    """
    wait_idle()
    vals = a.get("values") or {}
    # Normalise to an ordered list of [label_or_id, value] pairs: order matters to TBC (see guard_fill), and the
    # skill tbc_api_basics notes that dicts parsed from JSON may not keep their order inside IronPython
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
    """Tool command_ui_click: press a button (or select a tab by its name) in the open panel or a popup.

    a: {"button": text or id, "scope": None | "dialog:<i>" | "pane:<title>", "wait_seconds": default 1.0}.
    Waits for TBC to be idle, presses the button asynchronously inside TBC (so a popup it opens cannot block
    the bridge), then reports what happened (ui_after). Returns {"pressed": text} or {"selected_tab": name},
    plus "after". Changes TBC: whatever the button does.
    """
    wait_idle()
    r = run_ipy("command_ui", "click", {"button": a["button"], "scope": a.get("scope")})
    r["after"] = ui_after(float(a.get("wait_seconds", 1.0)))
    return r


def view_covered_by_other_app():
    """Sample a grid of points over the view's screen area; if any top-level window there belongs to another
    process, return a description (privacy: never screenshot other applications).

    The screenshot copies pixels from the SCREEN (view.screenshot uses Graphics.CopyFromScreen), so anything
    lying on top of TBC's view would be captured. This checks a 5 x 5 grid of points (5 %, 25 %, 50 %, 75 %,
    95 % across and down the active view's screen rectangle) with WindowFromPoint and compares the owning
    process of each window's root window with TBC's pid.
    Returns None when every point shows a TBC window (also when not on Windows, or when TBC's pid is unknown
    because the info file has none), else a short description of the first problem point. One bridge call (view.screen_rect); otherwise local Win32 calls only.
    """
    if os.name != "nt":
        return None
    import ctypes
    import ctypes.wintypes as W
    u = ctypes.windll.user32
    rc = run_ipy("view", "screen_rect", {})
    pid = (read_info() or {}).get("pid")
    # Declare HWND return types so window handles are not truncated to a C int
    u.WindowFromPoint.restype = W.HWND
    u.GetAncestor.restype = W.HWND
    for fx in (0.05, 0.25, 0.5, 0.75, 0.95):
        for fy in (0.05, 0.25, 0.5, 0.75, 0.95):
            x = int(rc["left"] + rc["width"] * fx)
            y = int(rc["top"] + rc["height"] * fy)
            h = u.WindowFromPoint(W.POINT(x, y))
            if not h:
                return "nothing visible at %d,%d" % (x, y)  # no window at all there: also refuse the screenshot
            p = W.DWORD()
            # GetAncestor(h, 2) = GA_ROOT: the top-level window that contains the control under the point
            u.GetWindowThreadProcessId(u.GetAncestor(h, 2) or h, ctypes.byref(p))
            if pid and p.value != pid:
                return "another application's window at %d%%,%d%% of the view" % (fx * 100, fy * 100)
    return None


def t_view(a):
    """Tool tbc_view: what the user is looking at in TBC's active Plan View.

    a: {"action": "info" (default) | "screenshot" | "set_extents", "units": "display" | "meters",
        "max_width": screenshot width limit in pixels (default 1400), "min"/"max": {"x", "y"} or
        "zoom_extents": true for set_extents}.
    info:        visible area (min, max, center, width, height; x = easting, y = northing) and open views.
    screenshot:  refused (BridgeError) when another application covers the view (privacy, see
                 view_covered_by_other_app); otherwise view.screenshot saves a PNG in the temp folder and the
                 "_image_path" key makes handle() attach it to the MCP result as an image.
    set_extents: zooms the user's view (changes what the user sees, not the project); returns the new info.
    """
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
        r["_image_path"] = r["path"]  # handle() pops this key and attaches the PNG
        return r
    if act == "set_extents":
        if a.get("zoom_extents"):
            return run_ipy("view", "set_extents", dict(args, zoom_extents=True))
        return run_ipy("view", "set_extents", dict(args, min=a["min"], max=a["max"]))
    raise BridgeError("action must be info, screenshot or set_extents")


def post_click(hwnd, x, y):
    """Deliver a genuine left click to a window's client point (TBC sees it exactly like a user click).

    hwnd: window handle; x, y: client coordinates in pixels. Posts WM_LBUTTONDOWN + WM_LBUTTONUP (asynchronous).
    NOTE: nothing in the server calls this at present - ui_grid's clicks are delivered inside TBC by
    command_ui.grid_click (in-process mouse messages).
    """
    import ctypes
    u = ctypes.windll.user32
    lp = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)  # lParam = MAKELPARAM(x, y): y in the high word
    u.PostMessageW(hwnd, 0x0201, 0x0001, lp)  # WM_LBUTTONDOWN, MK_LBUTTON
    u.PostMessageW(hwnd, 0x0202, 0x0000, lp)  # WM_LBUTTONUP


def t_ui_grid(a):
    """Tool ui_grid: read and edit tables inside TBC panels, popups and panes (e.g. Layer Manager).

    a: {"action": "read" (default) | "set" | "click", "scope": None | "dialog:<i>" | "pane:<title>",
        "grid": grid name if there are several, "where": {column: value} filter for read, "limit" (read, 200),
        "row": {column: value} matching exactly one row, or a row index (set/click), "column": name or header,
        "value": new value (set), "wait_seconds"}.
    read:  command_ui.grid_read -> {"grid", "columns", "row_count", "rows": [{column: value, "_row": index}]}.
    set:   checkbox columns are toggled with a real click (see below) and re-read to confirm ("now", "warning");
           other cells go through command_ui.grid_set (the grid's own edit path). Returns the result + "after".
    click: a genuine mouse click on one cell (icon cells such as Layer Manager's red-X Delete column).
    Changes TBC: set/click act like the user editing or clicking the grid; the tool description asks the AI to
    ask the user before deleting.
    """
    act = a.get("action", "read")
    base = {"scope": a.get("scope"), "grid": a.get("grid")}
    if act == "read":
        return run_ipy("command_ui", "grid_read", dict(base, where=a.get("where"), limit=a.get("limit", 200)))
    if act == "set":
        # Read the target row(s) and find the column first: a dict row is used as grid_read's filter, an integer
        # row is picked out by its "_row" index
        cur = run_ipy("command_ui", "grid_read", dict(base, where=a["row"] if isinstance(a["row"], dict) else None, limit=500))
        rows = cur["rows"] if isinstance(a["row"], dict) else [x for x in cur["rows"] if x["_row"] == a["row"]]
        col = next((c for c in cur["columns"] if a["column"].lower() in (c["name"].lower(), (c["header"] or "").lower())), None)
        if rows and col and col["type"] == "CheckBoxColumn":
            # TBC only commits checkbox changes from a real click: toggle by clicking if needed
            # (working_safely_in_tbc: setting them in code leaves TBC out of sync)
            want = a["value"] if isinstance(a["value"], bool) else str(a["value"]).lower() in ("1", "true", "yes", "on")
            if bool(rows[0].get(col["name"])) == want:
                return {"column": col["name"], "now": want, "changed": False}  # already as wanted: no click
            pt = run_ipy("command_ui", "grid_click", dict(base, row=a["row"], column=a["column"]))
            r = {"column": col["name"], "clicked": True}
            r["after"] = ui_after(float(a.get("wait_seconds", 0.8)))
            # Re-read the clicked row to report the value TBC actually holds now. pt["row"] is the grid row index,
            # used here as a position in the unfiltered row list.
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
    """Tool tbc_dialogs: list, answer, fill or back out of the popups TBC is showing.

    a: {"action": "list" (default) | "click" | "fill" | "dismiss" | "file", "index": TBC popup index (default 0),
        "button": button text, "native": bool (target a standard Windows dialog), "force": bool,
        "values"/"press" (fill), "path" (file), "wait_seconds"}.
    list:    dialogs_snapshot() - read-only.
    dismiss: safe_dismiss() - Cancel/Close/No/Abort only, otherwise X; license popups always X.
    click:   presses `button`. Any button other than Cancel/Close/No/Abort is refused while a license popup is
             open, unless force=true (only if the user asked; licensing is the user's business). Tries the TBC
             popup at `index` first and falls back to native dialogs when there is no such popup or button.
    fill:    command_ui_fill scoped to "dialog:<index>".
    file:    types `path` into a standard Open/Save dialog and presses Open/Save (native_dialogs set_file).
    click and file are followed by ui_after. Changes TBC: whatever the pressed button does.
    """
    act = a.get("action", "list")
    if act == "list":
        return {"dialogs": dialogs_snapshot()}
    if act == "dismiss":
        return {"actions": safe_dismiss()}
    if act == "click":
        btn = a["button"]
        if not a.get("force") and btn.strip().lower() not in SAFE_BUTTONS:
            # Conservative: refused if ANY open popup is a license popup, not only the one being clicked
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
                # Matches command_ui's messages "No modal dialog #i is open" (_root) and "No button '...'"
                # (_find_button): then try the standard Windows dialogs, which command_ui does not list
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
# The knowledge base itself is knowledge.py (K); these handlers add what needs TBC: license flags on skills that
# mention unlicensed commands, the running TBC release stamped on new knowledge, and compile checks / runs of
# saved scripts inside TBC. The object handlers (delete_entities, get_entity, create_points) and the offline
# help tool (tbc_help) follow in their own sub-sections. (tbc_memory and tbc_preferences are further down.)
def t_skills(a):
    """Tool tbc_skills: the knowledge base of documented how-tos (knowledge/skills/**/*.skill.md).

    a: {"action": "list" (default) | "search" | "read" | "save" | "append_version_section", plus per action:
        category (list/save), query + kinds + limit (search), name (read/save/append), description, body,
        requires_write, parameters, overwrite (save), release (append_version_section)}.
    list:   {"knowledge_dir", "skills"} (local only).
    search: K.search across skills, scripts, lessons and recorded panels, annotated with license flags.
    read:   the skill's markdown text; prefixed with a NOTE when it mentions commands (in `backticks`) that this
            user's license lacks.
    save / append_version_section: written by knowledge.py (a skill from another TBC release cannot be
            overwritten; append adds a '## TBC <release>' section). The running TBC release is looked up first
            (tbc_version) so the new text is stamped with it; without TBC, K.current_release() decides.
    Raises K.KnowledgeError for bad names / actions. Writes files under knowledge/ for save and append.
    """
    act = a.get("action", "list")
    if act == "list":
        return {"knowledge_dir": K.ROOT, "skills": K.list_skills(a.get("category"))}
    if act == "search":
        return {"results": annotate_license(K.search(a["query"], a.get("kinds"), int(a.get("limit", 15))))}
    if act == "read":
        text = K.read_skill(a["name"])
        lm = licensed_map()
        # lm is {} when TBC is not reachable: then no license note can be given
        bad = sorted(set(m for m in CMD_REF_RE.findall(text) if lm.get(m.lower()) is False)) if lm else []
        if bad:
            text = ("NOTE: this skill mentions commands that THIS user's TBC license does not include: %s. "
                    "Skills may have been written on a machine with a different license.\n\n" % ", ".join(bad)) + text
        return text
    if act in ("save", "append_version_section"):
        try:
            tbc_version()  # stamp new knowledge with the release actually running
        except BridgeError:
            pass  # TBC not reachable: K.current_release() gives the release seen earlier, else the baseline
    if act == "save":
        return K.save_skill(a["name"], a.get("category", "general"), a.get("description", ""), a["body"],
                            bool(a.get("requires_write")), a.get("parameters"), bool(a.get("overwrite")))
    if act == "append_version_section":
        return K.append_version_section(a["name"], a["body"], a.get("release"))
    raise K.KnowledgeError("action must be list, search, read, save or append_version_section")


def _compile_check(code):
    """Syntax-check a script body before it is saved; returns a one-line verdict string.

    Preferred: compile it inside TBC's IronPython 3.4 (the interpreter that will run it) via execute_python,
    without running it (compile() only) and without a transaction; 30 s timeout. The code travels as a JSON
    string so quotes and newlines survive. If TBC / the bridge is not running or not reachable, falls back to
    CPython's compile() locally (which does not catch IronPython-only differences). A SyntaxError in either
    case propagates (from TBC as a BridgeError), so a script that does not compile is not saved.
    """
    try:
        call_bridge("execute_python", {"code": "import json as _j\ncompile(_j.loads(%r), '<script>', 'exec')" % json.dumps(code),
                                       "transaction": False}, timeout=30)
        return "compiled OK in TBC's IronPython"
    except BridgeError as ex:
        # "not running" / "not reachable" match bridge_endpoint's and call_bridge's no-bridge messages
        if "not running" in str(ex) or "not reachable" in str(ex):
            compile(code, "<script>", "exec")
            return "TBC not running: syntax checked with CPython only (IronPython 3.4 may still differ)"
        raise


def t_script(a):
    """Tool tbc_script: saved, reusable IronPython scripts (knowledge/scripts/<name>.py) that run inside TBC.

    a: {"action": "list" (default) | "read" | "save" | "run" | "delete", "name", "description",
        "mode": "read" | "write", "parameters": [{name, type, required, default, description}], "code",
        "args": {...} (run), "overwrite": bool (save)}.
    list/read:  local knowledge only.
    delete:     K.delete_script retires the script into scripts/_archive (not destroyed).
    save:       stamps the running TBC release (tbc_version), builds the script file with its JSON metadata
                header, compile-checks the body (_compile_check) and saves it; overwriting bumps
                script_version and archives the old file (knowledge.py). Returns the save result + "check".
    run:        binds `args` to the declared parameters (K.bind_args), prepends them as the dict `args`, and runs
                the body through execute_python; mode "write" runs as one undo-able transaction that rolls back
                on error, "read" without a transaction. Returns execute_python's {"stdout", "result"} plus
                "script", "script_version", "args" and a "version_note" when the script was verified on other
                TBC releases than the one running.
    Raises K.KnowledgeError (names, metadata, arguments) or BridgeError (TBC side).
    """
    act = a.get("action", "list")
    if act == "list":
        return {"knowledge_dir": K.ROOT, "scripts": K.list_scripts()}
    if act == "read":
        return K.read_script(a["name"])
    if act == "delete":
        return K.delete_script(a["name"])
    if act == "save":
        try:
            tbc_version()  # so build_script records the release actually running in tbc_versions
        except BridgeError:
            pass
        text = K.build_script(a["name"], a.get("description", ""), a.get("mode", "read"), a.get("parameters"), a["code"])
        meta, body = K.parse_script(text)
        check = _compile_check(body)  # raises (nothing saved) when the code does not compile
        r = K.save_script(a["name"], text, bool(a.get("overwrite")))
        r["check"] = check
        return r
    if act == "run":
        meta, body = K.parse_script(K.read_script(a["name"]))
        bound = K.bind_args(meta, a.get("args"))
        # The script sees its arguments as the dict `args`, next to execute_python's usual globals
        code = "import json as _j\nargs = _j.loads(%r)\n" % json.dumps(bound) + body
        r = call_bridge("execute_python", {"code": code, "transaction": meta.get("mode") == "write"})
        r["script"] = meta["name"]
        r["script_version"] = meta.get("script_version", 1)
        r["args"] = bound
        try:
            # Scripts saved before versioning have no tbc_versions: they count as verified on the baseline release
            note = K.version_note(meta.get("tbc_versions") or [K.BASELINE_RELEASE]) if tbc_version() else None
        except BridgeError:
            note = None
        if note:
            r["version_note"] = note + " If it works, save it again (tbc_script save overwrite=true) to record this release."
        return r
    raise K.KnowledgeError("action must be list, read, save, run or delete")


# ---------------------------------------------------------------------------
# Object handlers built on the bridge: delete_entities, get_entity, create_points
# ---------------------------------------------------------------------------
# IronPython snippets run through execute_python (transaction=False, read-only). The caller prepends
# "args = [...]" (a list of serial numbers); each snippet sets `result`.
# EXISTS_CODE: which of the serials still exist in the project (used by delete_entities and tests/survey_cogo_tests.py)
EXISTS_CODE = r"""
from System import UInt32
result = [int(s) for s in args if prj.Concordance.Lookup(UInt32(int(s))) is not None]
"""
# LAYER_TYPE_CODE: which of the serials are layers. Not referenced anywhere in the repository at present.
LAYER_TYPE_CODE = r"""
from System import UInt32
result = [int(s) for s in args if prj.Concordance.Lookup(UInt32(int(s))).GetType().Name == 'Layer']
"""


# IMPORT_RECORD_CODE: which of the serials are import records (FileProperties objects, one per imported file),
# with the imported file's name - delete_entities refuses to delete those (see there)
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
    graphics-engine crashes on 2026-10-13, so it is no longer used.

    Tool delete_entities. a: {"serials": [int, ...], "allow_import_records": bool (only if the user asks)}.
    Steps: find which serials exist -> refuse import records (FileProperties) unless allowed -> wait_idle ->
    select them -> license check of "delete" -> pace_command -> run TBC's "delete" command -> 1 s + wait_idle
    -> check none are left -> clear the selection.
    Returns {"deleted": [serials], "not_found": [serials that did not exist], "method": ...}.
    Raises BridgeError when import records are included, or when objects survive the Delete command (the
    message lists the survivors and any open popups, e.g. a confirmation TBC asked).
    Changes TBC: deletes objects (one TBC Delete, undoable with Ctrl+Z) and changes / clears the selection.
    The bridge still has its own h_delete_entities (raw removal); this server no longer calls it.
    """
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
    # TBC's Delete command acts on the current selection, exactly as when the user presses the Delete key
    call_bridge("set_selection", {"serials": existing})
    check_license("delete")
    pace_command()
    call_bridge("run_command", {"key": "delete"})  # asynchronous in TBC: returns before the delete has run
    time.sleep(1.0)  # give the queued command a moment to start before checking whether TBC is computing
    wait_idle()
    # Verify instead of trusting the command: which of the objects are still there?
    left = call_bridge("execute_python", {"code": "args = %r\n" % existing + EXISTS_CODE, "transaction": False})["result"]
    try:
        call_bridge("set_selection", {"serials": []})  # leave TBC tidy: clear the selection this tool made
    except BridgeError:
        pass
    if left:
        ds = dialogs_snapshot()
        raise BridgeError("TBC's Delete command left %d of %d objects (serials %s). Popups: %s" % (
            len(left), len(existing), left[:20], [(d.get("title"), d.get("message")) for d in ds]))
    return {"deleted": existing, "not_found": missing, "method": "TBC Delete command (undo with Ctrl+Z)"}


# LINE_ELEV_CODE: effective elevation at each vertex of a linestring (first 2000 vertices, like the bridge's
# get_entity). For every vertex it accumulates the 2D distance along the line from the first vertex and asks the
# linestring itself for the elevation there (UpdateSnapElevation fills the ref Point3D's Z). NaN ("z != z")
# becomes None. Values are converted from meters to display units unless args["units"] == "meters".
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
    element (vertex z stays undefined), so evaluate the elevation along the line at each vertex.

    Tool get_entity. a: {"serial": int, "property_filter": substring of property names, "units"}.
    Returns the bridge's get_entity result (summary, readable .NET properties, "vertices" for linestrings).
    Only for linestrings with vertices whose z is None (the bridge turns NaN into None): those vertices get the
    elevation from LINE_ELEV_CODE and "z_source": "vertical profile". If that extra lookup fails the plain
    result is returned. Read-only.
    """
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
            pass  # the elevations are a bonus: never fail get_entity because of them
    return e


# NEXT_ID_CODE: the highest all-digit point name in the project ("max_numeric", 0 if none) and which of the
# requested names (args) are already taken
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
    """Numeric IDs by default (user preference); feature codes go through the verified Create Point panel.

    Tool create_points. a: {"points": [{"name"?, "easting", "northing", "elevation"?, "feature_code"?,
    "layer"?}], "start_id"?: int, "allow_duplicates": bool, "units": "display" | "meters"}.
    IDs: names given by the caller are checked against the project (BridgeError if taken, unless
    allow_duplicates); points without a name get consecutive numbers from start_id, else from the highest
    numeric point ID + 1 (working_safely_in_tbc: point IDs are plain numbers, descriptions go in Feature code).
    Two paths:
      no feature codes at all -> the bridge's create_points API call: fast, one undo step.
      any feature code        -> EVERY point is typed into TBC's Create Point panel ("addpoint") and Add is
                                 pressed, so TBC does its own feature-code processing (Point.FeatureCode is
                                 read-only through the API - tbc_api_basics). About 1 s per point. Layers are
                                 created first through the API; the panel is closed at the end.
    Returns the bridge result + "method", or for the panel path {"method", "created", "ids" (first 50),
    "problems" (first 20 points with errors, popups or field messages)}.
    Changes TBC: creates points (and layers); the panel path also opens and closes a command and may dismiss popups.
    """
    pts = [dict(p) for p in a["points"]]
    units = a.get("units", "display")
    wanted = [str(p["name"]) for p in pts if p.get("name") not in (None, "")]
    info = call_bridge("execute_python", {"code": "args = %r\n" % wanted + NEXT_ID_CODE, "transaction": False})["result"]
    if info["taken"] and not a.get("allow_duplicates"):
        raise BridgeError("Point ID(s) already exist: %s. Omit 'name' to get the next free numbers, or pass "
                          "allow_duplicates=true." % info["taken"][:20])
    # Note: numbers counted up from an explicit start_id are not checked against existing IDs
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
    # The panel takes values in display units: convert meters input with the project's factor
    f = 1.0
    if units == "meters":
        f = call_bridge("project_info")["meters_to_display_factor"]
    layers = set(p["layer"] for p in pts if p.get("layer"))
    for l in layers:
        call_bridge("create_layer", {"name": l})  # FindOrCreateLayer: existing layers are left as they are
    st = t_command_ui_open({"key": "addpoint"})
    if not st.get("command"):
        raise BridgeError("Create Point panel did not open: %s" % json.dumps(st)[:400])
    made, problems = [], []
    try:
        for p in pts:
            # Fields in the order a user would fill the Create Point panel; labels as shown on screen
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
        # Leave TBC tidy even when a point failed half-way
        try:
            run_ipy("command_ui", "close", {})
        except BridgeError:
            pass
    return {"method": "Create Point panel (feature codes)", "created": len(made), "ids": made[:50] + (["..."] if len(made) > 50 else []),
            "problems": problems[:20]}


# ---------------------------------------------------------------------------
# TBC's installed help (offline, tbc_help.py)
# ---------------------------------------------------------------------------
# HELP_TOPIC_CODE: the HelpTopic id of a command (args = the command key; None if the key does not exist).
# A command's help page is <HelpTopic>.htm in TBC's installed help (tbc_help.py).
HELP_TOPIC_CODE = r"""
cl = TrimbleOffice.TheOffice.CommandProcessor.CommandList
k = args.lower()
result = str(getattr(cl[k], 'HelpTopic', '') or '') if cl.ContainsKey(k) else None
"""


def t_help(a):
    """Tool tbc_help: TBC's own installed help, read offline (tbc_help.py, TBC_HELP_DIR).

    a: {"action": "search" (default) | "read", "query", "limit" (15), "topic", "command", "max_chars" (6000)}.
    search: word search over the help topics -> {"results": [{"topic", "title"}]} (no TBC needed).
    read:   a topic's {"title", "keywords", "text", "topic"} by topic id, or by command key - then TBC is asked
            (one read-only execute_python call) for that command's HelpTopic. BridgeError when the command
            has no help topic or the topic file is missing.
    """
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
    """Close the open command / pane (command_ui.close), ignoring bridge errors. Used in finally blocks so the
    Import / Export pane never stays open after a tool call (leave TBC tidy)."""
    try:
        run_ipy("command_ui", "close", {})
    except BridgeError:
        pass


def t_export(a):
    """Export through TBC's Export pane: category tab -> exporter -> data -> target file -> Export.

    Tool tbc_export. a: {"action": "export" (default) | "formats", "category": tab name (GIS, CAD, Custom ...),
    "format": exporter name exactly as listed, "serials": objects to export, "path": FULL target file path,
    "settings": [[field, value], ...] exporter options, "overwrite": bool, "wait_seconds" (default 3)}.
    formats: {"formats": {category: [exporter names]}} for one or all categories.
    export:  refuses a relative path (TBC's default target would be the project folder) and an existing file
             unless overwrite=true; chooses the exporter (import_export.export_choose), types the serials into
             the exporter's data box (the field whose value reads "Selected: N"), the path into TargetFileBox and
             any settings, presses Export, waits for TBC to be idle and reports the file size on disk:
             {"exported": size > 0, "path", "bytes", "exporter", "fill"}.
    Side effects: opens the Export pane (always closed again in `finally`), writes the target file.
    Note: with overwrite=true an existing file's size also counts as "exported", even if TBC wrote nothing.
    """
    act = a.get("action", "export")
    t_command_ui_open({"key": "export"})  # license check, pacing, panel settle - like any command
    try:
        if act == "formats":
            return {"formats": run_ipy("import_export", "export_formats", {"category": a.get("category")})}
        path = a.get("path") or ""
        if not os.path.isabs(path):
            raise BridgeError("path must be a full file path (the default would be the project folder)")
        if os.path.exists(path) and not a.get("overwrite"):
            raise BridgeError("%s already exists; pass overwrite=true to replace it" % path)
        chosen = run_ipy("import_export", "export_choose", {"category": a["category"], "format": a["format"]})
        time.sleep(FILL_SETTLE_S)  # settle pause after choosing the exporter, before its fields are read
        st = ui_state(include_text=False)
        # The object-selection box of an exporter shows "Selected: N"; that is how it is recognised
        data_box = [f["id"] for f in st.get("fields", []) if "Selected:" in str(f.get("value"))]
        values = []
        if a.get("serials"):
            if not data_box:
                raise BridgeError("This exporter has no data selection box; fields: %s" % [f["id"] for f in st.get("fields", [])])
            values.append([data_box[0], list(a["serials"])])  # multi-select boxes take a list of serials
        values.append(["TargetFileBox", path])
        values += [list(p) for p in (a.get("settings") or [])]
        r = t_command_ui_fill({"values": values, "press": "Export", "wait_seconds": float(a.get("wait_seconds", 3))})
        wait_idle()
        size = os.path.getsize(path) if os.path.exists(path) else 0
        return {"exported": size > 0, "path": path, "bytes": size, "exporter": chosen, "fill": r}
    finally:
        _close_pane()


def t_import(a):
    """Import through TBC's Import pane: scan a folder (shows the importer TBC picked per file), then import.

    Tool tbc_import. a: {"action": "scan" (default) | "import", "folder": existing folder, "files": [file
    names from the scan], "confirm": bool, "wait_seconds" (default 3), "allow_cad" (ignored, kept for
    compatibility)}.
    scan:   points the Import pane at the folder and waits (up to 60 s) for TBC's importer detection; returns
            import_export.import_state: {"folder", "scanning", "files_left_to_scan", "files": [{"name",
            "importer", "folder", "already_imported"}], "selected"}. The AI must check the detected importer
            (e.g. a P,N,E CSV detected as P,E,N) before importing.
    import: refused without confirm=true (importing changes the project and TBC copies each file into the
            project folder). Selects the files, presses Import, presses Import in TBC's Import Format Editor
            wizard if it appears (custom / CSV formats), waits for Compute Project, logs TBC error popups.
            Returns {"imported", "importers", "after", "format_editor", "waited_for_compute_s", "popups_left",
            "errors", "note"}.
    Side effects: opens the Import pane; closes it again unless a TBC error popup is still showing (then it is
    left as it is for the user to see). Import adds data to the project and copies files.
    """
    act = a.get("action", "scan")
    folder = a.get("folder") or ""
    if not os.path.isdir(folder):
        raise BridgeError("folder must be an existing folder: %r" % folder)
    t_command_ui_open({"key": "import"})
    done_ok = False
    try:
        st = run_ipy("import_export", "import_folder", {"folder": folder})
        t0 = time.time()
        # TBC picks an importer per file while its view model reports "scanning": poll until done (max 60 s)
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
        # Pressed through command_ui_click so the usual idle wait and popup report (ui_after) apply
        r = t_command_ui_click({"button": "Import", "wait_seconds": float(a.get("wait_seconds", 3))})
        steps = []
        # custom/CSV formats open the 'Import Format Editor' wizard; its Import button imports with that format
        for d in dialogs_snapshot():
            if (d.get("title") or "").startswith("Import Format Editor") and "Import" in (d.get("buttons") or []):
                steps.append(t_tbc_dialogs({"action": "click", "index": d["index"], "button": "Import"}))
        waited = wait_idle()  # the tool promises to wait for Compute Project before reporting
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
        # Close the pane, except while a TBC error popup is up: then everything stays as it is for the user
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
# In-memory cache of this server run's profile and when it was last confirmed (time.time())
_lic = {"profile": None, "checked": 0.0}


def license_profile(refresh=False):
    """The current license profile. Built when the MCP server starts, saved to
    %LOCALAPPDATA%\\TBC-MCP\\license\\<fingerprint>.json (this machine only, never in the repo).
    Profiles are keyed by a hash of the license key + licensed features; no user names or emails are stored.

    More precisely: built on the FIRST call in each server run (bridge_status, tbc_license, or the license
    flags of tbc_skills search/read), not at process start.
    refresh: True = rebuild now (tbc_license action=refresh).
    Caching: within 600 s (10 min) of the last check the in-memory profile is returned without asking TBC.
    After that the fingerprint is asked again (ipy/license.py fingerprint: SHA-256 of TBC's license key id and
    the licensed feature names, first 16 hex digits); an unchanged license reloads its saved file, a changed
    license (new fingerprint) gets a new profile built and saved.
    Returns the profile dict from license.profile ("fingerprint", "key_type", "subscription_expires",
    "maintenance_expires", "features_licensed", "features_unlicensed", "commands": {key: {"licensed",
    "caption", "needs_any_of"}}) plus "created", "summary" (counts) and, when it was built in this call,
    "_new": True (in memory only).
    Side effects: one or two read-only bridge calls; writes the profile file under LICENSE_DIR; registers the
    fingerprint with P.add_private so it never appears in a shared project note.
    Raises BridgeError when TBC is not reachable.
    """
    now = time.time()
    if _lic["profile"] is None:
        refresh = True  # every new MCP server instance rebuilds the profile (takes ~0.5 s), so it is always current
    if _lic["profile"] is not None and not refresh and now - _lic["checked"] < 600:
        return _lic["profile"]
    fp = run_ipy("license", "fingerprint", {})["fingerprint"]
    P.add_private(fp, "a license detail")  # license data never goes into shared project notes
    path = os.path.join(LICENSE_DIR, fp + ".json")
    prof = None
    if os.path.exists(path) and not refresh:
        try:
            with open(path, "r", encoding="utf-8") as f:
                prof = json.load(f)
        except ValueError:
            prof = None  # damaged file: rebuild it below
    if prof is None:
        log("building license profile %s for this MCP instance" % fp)
        prof = run_ipy("license", "profile", {})  # every command's license status, about 0.5 s inside TBC
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
        prof["_new"] = True  # set after saving, so the file never carries it
    _lic["profile"], _lic["checked"] = prof, now
    return prof


def licensed_map():
    """{command key (lower): True/False/None} from the cached profile, or {} if TBC isn't reachable.

    Used to flag knowledge that mentions unlicensed commands (annotate_license, t_skills read). An empty dict
    means "unknown", and callers then skip the license flags rather than fail.
    """
    try:
        return dict((k.lower(), v.get("licensed")) for k, v in license_profile().get("commands", {}).items())
    except BridgeError:
        return {}


def t_license(a):
    """Tool tbc_license: what THIS user's TBC license allows.

    a: {"action": "summary" (default) | "refresh" | "check" | "unlicensed", "keys": [command keys] (check),
        "contains": filter on key or caption (unlicensed), "limit": max rows (unlicensed, default 200)}.
    summary / refresh: fingerprint, dates, feature list with expiry and command counts (refresh rebuilds the
            profile first).
    check:  a LIVE check of the given keys (command_ui.license), not the cached profile.
    unlicensed: commands whose cached status is licensed=False, optionally filtered.
    Every action loads the profile first (license_profile), so all of them need TBC. Read-only in TBC;
    refresh rewrites the local profile file.
    """
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
        live = run_ipy("command_ui", "license", {"keys": a["keys"]})  # live, same check as before every command
        for k in a["keys"]:
            out[k] = live.get(k)
        return {"commands": out}
    if act == "unlicensed":
        f = (a.get("contains") or "").lower()
        rows = [{"key": k, "caption": v.get("caption"), "needs_any_of": v.get("needs_any_of")}
                for k, v in sorted(cmds.items()) if v.get("licensed") is False and (not f or f in k.lower() or f in (v.get("caption") or "").lower())]
        return {"count": len(rows), "commands": rows[:int(a.get("limit", 200))]}
    raise BridgeError("action must be summary, refresh, check or unlicensed")


# A command key written in a skill as inline code: a backticked word that starts with a letter and is 3-61
# letters, digits, '_' or '.' long, e.g. `addpoint`. Every match is looked up in licensed_map(); only words that
# ARE command keys there and are unlicensed get flagged, so other backticked words are harmless.
CMD_REF_RE = re.compile(r"`([A-Za-z][A-Za-z0-9_.]{2,60})`")


def annotate_license(results):
    """Flag knowledge hits that rely on commands this user's license doesn't include.

    results: K.search hits (dicts with "type": "command" | "lesson" | "skill" | "script"). Mutated in place
    and returned:
      command hits get "licensed" (True / False / None),
      lesson hits whose topic is a command key get "licensed",
      skill hits get "unlicensed_commands_mentioned" (backticked command keys the license lacks; reads the skill).
    Returns the results unchanged when the license is unknown (TBC not reachable).
    """
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


# ---------------------------------------------------------------------------
# Running TBC release, bridge status, user preferences
# ---------------------------------------------------------------------------
# Cache of tbc_version() for this server run
_ver = {"value": None}
# VERSION_CODE: path of the running TBC executable and its ProductVersion (the build, e.g. 44.0.9666.28609)
VERSION_CODE = r"""
from System.Diagnostics import Process, FileVersionInfo
p = Process.GetCurrentProcess().MainModule.FileName
result = {'exe': p, 'build': str(FileVersionInfo.GetVersionInfo(p).ProductVersion)}
"""


def tbc_version(refresh=False):
    """{'release': '2026.10', 'build': '44.0.9666.28609'} of the running TBC. The build comes from the running exe;
    the release name (e.g. 26.10 -> 2026.10) from Windows' install record for that folder. Cached per server run.

    refresh: True = ask TBC again instead of using the cache.
    The install record is the Uninstall registry entry (HKLM, 64- and 32-bit views) whose DisplayName starts
    with "Trimble Business Center" (help packages excluded) and whose InstallLocation is the running exe's
    folder. Its DisplayVersion "NN.N" becomes "20NN.N"; without such an entry the release is "build <build>".
    Side effect: K.set_tbc_version(...) so everything knowledge.py writes from now on is stamped with this
    release (skills, lessons, scripts, panel layouts) and version notes compare against it.
    Raises BridgeError when TBC is not reachable (callers that only stamp knowledge ignore it).
    """
    if _ver["value"] and not refresh:
        return _ver["value"]
    info = call_bridge("execute_python", {"code": VERSION_CODE, "transaction": False}, timeout=30)["result"]
    release = None
    try:
        import winreg  # Windows-only module: elsewhere the release falls back to the build
        folder = os.path.dirname(info["exe"]).rstrip("\\").lower()
        for root in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                     r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
            try:
                k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root)
            except OSError:
                continue
            for i in range(winreg.QueryInfoKey(k)[0]):  # [0] = number of subkeys (one per installed product)
                try:
                    sk = winreg.OpenKey(k, winreg.EnumKey(k, i))
                    name = winreg.QueryValueEx(sk, "DisplayName")[0]
                    loc = str(winreg.QueryValueEx(sk, "InstallLocation")[0]).rstrip("\\").lower()
                    if name.startswith("Trimble Business Center") and "help" not in name.lower() and loc == folder:
                        dv = str(winreg.QueryValueEx(sk, "DisplayVersion")[0])
                        # "26.10" -> "2026.10" (two digits, dot, digits); any other format is kept as it is
                        release = ("20" + dv) if re.match(r"^\d\d\.\d+$", dv) else dv
                except OSError:
                    continue  # entries without DisplayName / InstallLocation are skipped
    except ImportError:
        pass
    v = {"release": release or ("build " + info["build"]), "build": info["build"]}
    _ver["value"] = v
    K.set_tbc_version(v["release"], v["build"])
    return v


def t_bridge_status(a):
    """Tool bridge_status: is the bridge reachable, which TBC is running, and this user's license summary.

    Returns the bridge's ping answer ({"pong", "bridge_version", "in_tbc", "import_errors"}) plus
      "tbc":     {"release", "build", "knowledge_baseline", "note"} - note is set when the running release is
                 not the knowledge base's baseline (2026.10), telling the AI to ADD knowledge, never delete;
      "license": fingerprint, new_profile, summary, subscription_expires (builds the profile on first use).
    Each extra part reports {"error": ...} instead of failing the call. Raises BridgeError only when the ping
    itself fails (bridge not running: the message tells the user how to start it). Read-only in TBC.
    """
    r = call_bridge("ping", timeout=10)  # short timeout: a status check should answer quickly
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
    """Tool tbc_preferences: the user's standing rules (knowledge/preferences.json, via knowledge.py).

    a: {"action": "list" (default) | "add" | "update" | "remove", "text", "topic", "id"}.
    Local only, TBC is not touched. The preferences are appended to INSTRUCTIONS in every initialize answer
    (handle -> K.prefs_text), so they reach every AI chat. Raises K.KnowledgeError for bad input.
    """
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
# A job is matched by folder: the open .vce belongs to the job whose linked folder contains it (projects.py).
# So the server needs the full path of the project open in TBC, cached here: {"path": str or None, "at": time}.
_active = {"path": None, "at": 0.0}
ACTIVE_PATH_CODE = "result = str(prj.ProjectName)"   # TBC 2026: ProjectName is the full .vce path


def active_project_path(refresh=False):
    """Full path of the project open in TBC, or None (no project, unsaved, or TBC unreachable). Cached for 30 s so
    attaching project notes costs at most one small bridge call per half minute.

    refresh: True = ask TBC now (t_project_notes does, so a project just opened is seen).
    Never raises: a bridge error counts as "no project". One read-only execute_python call (15 s timeout).
    """
    if not refresh and time.time() - _active["at"] < 30:
        return _active["path"]
    try:
        path = call_bridge("execute_python", {"code": ACTIVE_PATH_CODE, "transaction": False}, timeout=15).get("result")
    except BridgeError:
        path = None
    remember_active_path(path)
    return _active["path"]


def remember_active_path(path):
    """Store `path` as the open project's path (and restart the 30 s cache). Anything that is not an absolute
    path (None, "", a bare name of an unsaved project) is stored as None, so it can't match a job folder."""
    _active["path"] = path if path and os.path.isabs(str(path)) else None
    _active["at"] = time.time()


def with_project_notes(result, path=None):
    """Adds the open project's shared notes to a result, once per project per server run.

    result: a tool result; only dicts are touched (anything else is returned as is).
    path:   the .vce path if the caller already knows it, else active_project_path() is used.
    Adds "project_notes" (from P.notes_once: the job's notes, files folder and files, with a hint) the first
    time a job is seen in this server run; later calls add nothing. Called from project_info, command_ui_open
    and execute_python results, so the AI meets the job's notes early without asking.
    Never raises (notes are advice); may cost one bridge call (active_project_path).
    """
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
    """Tool project_info: the bridge's project summary (name, path, units, counts, modified flag ...).

    Also refreshes the cached project path from the answer (no extra bridge call) and adds the job's shared
    "project_notes" the first time per project. Read-only in TBC.
    """
    info = call_bridge("project_info")
    if isinstance(info, dict):
        remember_active_path(info.get("path"))
        with_project_notes(info, _active["path"])
    return info


def t_execute_python(a):
    """Tool execute_python (only registered when ALLOW_PYTHON): run IronPython 3.4 code inside TBC.

    a: {"code": str, "transaction": bool (default True in the bridge: one undo step, rolled back on error)}.
    Passed straight to the bridge. Returns {"stdout": last 20000 chars of print output, "result": the code's
    `result` variable} plus "related_lessons" (lessons about TBC command keys named in the code,
    K.lessons_relevant_to) and, first time per project, "project_notes".
    Changes TBC: whatever the code does - the escape hatch, with full SDK access.
    """
    r = call_bridge("execute_python", a)
    if isinstance(r, dict):
        lessons = K.lessons_relevant_to(a.get("code", ""))
        if lessons:
            r["related_lessons"] = lessons
        with_project_notes(r)
    return r


def t_project_notes(a):
    """Tool tbc_project_notes: one job's notes and files in the project knowledge base shared with Civil 3D MCP
    and Project Analyzer (projects.py; folder from CIVIL3D_KNOWLEDGE_DIR).

    a: {"action": "list" (default) | "link" | "unlink" | "add" | "update" | "remove" | "files" | "read" |
        "locate", "project": job name (omit = the job the open .vce belongs to), "folder", "note", "id",
        "file", "path", "max_chars"}.
    Which job: a named project is used as is (no TBC call), except for link, where the open .vce's folder is
    the default folder; otherwise the open project's path is fetched fresh from TBC and matched by folder.
    Each action is one projects.py call (see there for rules: only TBC's own notes may be updated/removed,
    private values such as the bridge token and license fingerprint are refused, reference formats).
    Writes local shared-knowledge files for link/unlink/add/update/remove. Raises K.KnowledgeError.
    """
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
    if act == "locate":
        return P.locate(a.get("path"), name, path)
    raise K.KnowledgeError("action must be list, link, unlink, add, update, remove, files, read or locate")


def t_memory(a):
    """Tool tbc_memory: general lessons learned about TBC (knowledge/memory/lessons.jsonl, via knowledge.py).

    a: {"action": "list" (default) | "add" | "search" | "delete", "text", "topic", "command", "tags",
        "query", "id", "limit" (search, 20)}.
    add:    K.add_lesson (duplicates are returned "unchanged"; knowledge.py refuses job-specific details). The
            lesson's topic is `topic`, else `command`. With `command` the text is also stored as a note on that
            command's recorded panel, so it shows next time the command is opened. A lesson containing
            DANGER_WORDS makes check_known_danger require confirm=true for its topic: the answer says so.
    search / list: lessons (and recorded commands for search).
    delete: K.delete_lesson (knowledge.py only allows deleting lessons of the running release).
    add and delete first look up the running TBC release (tbc_version) for knowledge.py. Local files only.
    """
    act = a.get("action", "list")
    if act in ("add", "delete"):
        try:
            tbc_version()  # lessons are stamped with (and protected by) the running release
        except BridgeError:
            pass
    if act == "add":
        rec = K.add_lesson(a["text"], a.get("topic") or a.get("command"), a.get("tags"))
        if rec.get("action") == "unchanged":
            return rec  # already recorded: don't add the command note a second time either
        if a.get("command"):
            K.add_command_note(a["command"], a["text"])
        # Warn the AI when this lesson will turn on the confirm=true gate (check_known_danger)
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
# Parsed SDK docs, built on the first search_sdk_docs call and kept for the server run (None = not loaded yet)
_doc_index = None


def load_docs():
    """Index every member of the Macros SDK XML docs in SDK_DOCS (*.xml, .NET XML documentation format).

    Returns a list of tuples (assembly name, member id such as "T:Trimble.Vce.Coordinates.Point" or
    "M:...CreatePoint(...)", summary text, ["param: text", ...], returns text), whitespace collapsed.
    Files that do not parse or have no <assembly><name> are skipped. Cached in _doc_index (an empty list when
    the folder has no docs, so a missing folder is not searched again). Local only; logs the member count.
    """
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
            continue  # not a .NET XML doc file
        for m in root.iter("member"):
            s = m.find("summary")
            # itertext() includes text inside nested tags such as <see cref=...>; split/join collapses whitespace
            summary = " ".join("".join(s.itertext()).split()) if s is not None else ""
            params = ["%s: %s" % (p.get("name"), " ".join("".join(p.itertext()).split())) for p in m.findall("param")]
            r = m.find("returns")
            rows.append((asm, m.get("name", ""), summary, params,
                         " ".join("".join(r.itertext()).split()) if r is not None else ""))
    _doc_index = rows
    log("indexed %d SDK doc members from %s" % (len(rows), SDK_DOCS))
    return rows


def search_docs(query, kind=None, limit=40, detail=False):
    """Tool search_sdk_docs: search the offline Macros SDK reference. Returns plain text (not JSON).

    query:  regular expression, case-insensitive, matched against member ids; an invalid regex is searched
            for literally instead.
    kind:   "type" | "method" | "property" | "field" | "event" -> only ids starting with T: / M: / P: / F: / E:.
    limit:  max members listed (default 40); the total count is still reported.
    detail: (search_summaries) also match the summary text, and show params / returns for each hit.
    The header line reminds the AI that these docs are for an older SDK (v41, TBC 2024) and to verify members
    in the live TBC with execute_python + dir(). TBC is not touched.
    """
    rows = load_docs()
    if not rows:
        return "No SDK XML docs found in %s (set TBC_SDK_DOCS)." % SDK_DOCS
    try:
        pat = re.compile(query, re.I)
    except re.error:
        pat = re.compile(re.escape(query), re.I)  # e.g. "Point(" is not a valid regex: search it as plain text
    # .NET XML doc id prefixes: T: type, M: method, P: property, F: field, E: event
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
# Everything the AI can call. Each entry is a tuple:
#   (name, description, JSON Schema of the arguments, handler(args dict) -> JSON-able result, MCP annotations)
# handle() serves tools/list from it and dispatches tools/call through TOOL_MAP. The description strings are what
# the AI reads to decide how to use a tool (several tests check their wording), so change them with care.
# Annotations are hints for the client: readOnlyHint (does not change the TBC project), destructiveHint (may
# change or remove existing data), openWorldHint.
# Handlers named t_* are defined above; lambdas are direct pass-throughs to a bridge method (h_<name> in
# tbc_macro/TbcMcpBridge.py) or to a panel-engine action, with no extra safety layer.

# Shared schema for the "units" argument: inputs and outputs in the project's display units unless "meters"
# (TBC stores coordinates in meters internally; tbc_api_basics)
UNITS = {"type": "string", "enum": ["display", "meters"], "default": "display",
         "description": "'display' = the project's display units (default), 'meters' = TBC internal units."}


def obj(props, required=None):
    """JSON Schema for an object with exactly these properties (additionalProperties false, so a misspelt
    argument is rejected by schema-checking clients) and the given required names. Builds schemas only."""
    s = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        s["required"] = required
    return s


TOOLS = [
    # name, description, schema, handler(args) -> result, annotations
    # --- Project and data: read tools (all talk to TBC through the bridge) ---
    # bridge_status -> t_bridge_status: ping + TBC release/build + license profile (built on first use)
    ("bridge_status", "Check whether the TBC bridge macro is running and reachable; also loads (or on first use builds) this user's license profile.",
     obj({}), t_bridge_status, {"readOnlyHint": True}),
    # project_info -> t_project_info: bridge h_project_info; also caches the .vce path and adds project_notes once
    ("project_info", "Summary of the project open in TBC: name, file, display units, point/layer counts, modified flag. "
     "The first time per project it also returns the job's shared project notes (project_notes), if any.",
     obj({}), t_project_info, {"readOnlyHint": True}),
    # list_entities -> bridge h_list_entities directly (walks the WorldView container tree; paging via limit/offset)
    ("list_entities", "List graphical objects in the project (recursively through containers) with serial, type, name and layer. "
     "Also returns counts by type. Use filters and paging for big projects.",
     obj({"type_contains": {"type": "string", "description": "Case-insensitive substring of the type name, e.g. 'Linestring', 'Model3D', 'Point'."},
          "name_contains": {"type": "string"},
          "layer": {"type": "string", "description": "Exact layer name."},
          "graphical_only": {"type": "boolean", "default": True},
          "limit": {"type": "integer", "default": 200}, "offset": {"type": "integer", "default": 0}}),
     lambda a: call_bridge("list_entities", a), {"readOnlyHint": True}),
    # get_entity -> t_get_entity: bridge h_get_entity + effective linestring elevations (LINE_ELEV_CODE)
    ("get_entity", "Inspect one object by serial number: all readable .NET properties, plus vertices for linestrings.",
     obj({"serial": {"type": "integer"}, "property_filter": {"type": "string", "description": "Only properties whose name contains this."},
          "units": UNITS}, ["serial"]),
     t_get_entity, {"readOnlyHint": True}),
    # list_points / list_layers / list_surfaces / surface_elevation / get_selection -> bridge methods of the same
    # name, passed straight through
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
    # set_selection -> bridge h_set_selection: changes what is selected in TBC, not the project data
    ("set_selection", "Replace TBC's selection with the given serial numbers (empty list clears it).",
     obj({"serials": {"type": "array", "items": {"type": "integer"}}}, ["serials"]),
     lambda a: call_bridge("set_selection", a), {"readOnlyHint": False, "destructiveHint": False}),
    # --- Commands ---
    # list_commands -> t_list_commands: bridge h_list_commands + a live license flag per command
    ("list_commands", "Search TBC's command list (keys usable with run_command / command_ui_open). Each entry says "
     "whether the current TBC license allows it (licensed=false commands are skipped automatically).",
     obj({"contains": {"type": "string"}, "limit": {"type": "integer", "default": 300}}),
     t_list_commands, {"readOnlyHint": True}),
    # run_command -> t_run_command: license check, danger confirm, wait_idle, pacing, then fire-and-forget launch
    ("run_command", "Launch a TBC command by key (as the user would from the ribbon). Checks the license first and "
     "refuses unlicensed commands instead of triggering TBC's license popups. Runs asynchronously.",
     obj({"key": {"type": "string"}, "args": {"type": "array", "items": {}},
          "confirm": {"type": "boolean", "default": False, "description": "Required for commands the knowledge base marks as acting immediately; only after the user agreed."}}, ["key"]),
     t_run_command, {"readOnlyHint": False}),
    # --- Create and change ---
    # create_points -> t_create_points: next free numeric IDs; API path without feature codes, Create Point panel
    # with them
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
    # create_linestring / create_layer / set_properties -> bridge methods of the same name; each runs inside one
    # "MCP: ..." transaction in the bridge, so it is one undo step in TBC
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
    # delete_entities -> t_delete_entities: select + TBC's own Delete command (NOT the bridge's raw
    # h_delete_entities), refuses import records, verifies the objects are gone
    ("delete_entities", "Delete objects by serial number through TBC's own Delete command (select + Delete), then confirm they are gone. Works for layers too (select the layer serial). Ctrl+Z in TBC restores them. Import records (FileProperties, "
     "one per imported file) are refused: deleting them broke the next import on TBC 2026.10 - delete the imported data instead.",
     obj({"serials": {"type": "array", "items": {"type": "integer"}},
          "allow_import_records": {"type": "boolean", "default": False, "description": "only if the user asks"}}, ["serials"]),
     t_delete_entities, {"readOnlyHint": False, "destructiveHint": True}),
    # save_project -> bridge h_save_project (TrimbleOffice.TheOffice.CurrentProject.Save(); writes the .vce)
    ("save_project", "Save the current TBC project to disk.",
     obj({}), lambda a: call_bridge("save_project"), {"readOnlyHint": False, "destructiveHint": True}),
    # search_sdk_docs -> search_docs: offline, local XML files only; no TBC needed
    ("search_sdk_docs", "Search the TBC SDK API docs (offline). 'query' is a regex matched against member ids like "
     "'T:Trimble.Vce.Coordinates.Point' or 'M:...Point.CreatePoint(...)'. Use with execute_python to do things the other tools can't.",
     obj({"query": {"type": "string"}, "kind": {"type": "string", "enum": ["type", "method", "property", "field", "event"]},
          "search_summaries": {"type": "boolean", "default": False, "description": "Also match summary text and show params/returns."},
          "limit": {"type": "integer", "default": 40}}, ["query"]),
     lambda a: search_docs(a["query"], a.get("kind"), int(a.get("limit", 40)), bool(a.get("search_summaries"))),
     {"readOnlyHint": True}),
]

# Shared schema for the "values" argument of command_ui_fill and tbc_dialogs fill (see t_command_ui_fill:
# an object is turned into an ordered list of pairs before it goes to TBC)
FIELD_VALUES = {"description": "Fields to fill, IN ORDER. Either an object {label_or_id: value} or a list of "
                               "[label_or_id, value] pairs. Match by the on-screen label (e.g. 'Northing', 'Point ID') "
                               "or the field id from command_ui_inspect. Type values as a user would (display units). Object-picker fields "
                               "(kind entity): pass {\"serial\": n} or an integer serial to link an existing object; any "
                               "string (e.g. a point ID like \"4700486\") is typed as text for TBC to interpret. "
                               "Checkboxes take true/false; dropdowns take the option text.",
                "type": ["object", "array"]}

TOOLS += [
    # --- TBC command panels (the panel engine mcp_server/ipy/command_ui.py, run inside TBC) ---
    # command_ui_open -> t_command_ui_open: license/danger checks, idle wait, pacing, waits for the panel to settle,
    # records the layout to knowledge/commands/ (the only "write" is to the local knowledge base and opening a panel)
    ("command_ui_open", "Start a TBC command (key from list_commands) and return its panel: every field with its "
     "on-screen label, current value, dropdown options, and the buttons. Also returns what was remembered about this "
     "command from earlier sessions, and records the panel layout to the knowledge base.",
     obj({"key": {"type": "string"}, "wait_seconds": {"type": "number", "default": 15},
          "confirm": {"type": "boolean", "default": False, "description": "Required for commands marked as acting immediately; only after the user agreed."},
          "include_hidden": {"type": "boolean", "default": False, "description": "Include fields in collapsed/hidden sections."}},
         ["key"]),
     t_command_ui_open, {"readOnlyHint": False, "destructiveHint": False}),
    # command_ui_inspect -> t_command_ui_inspect: command_ui.state (+ popups); read-only in TBC
    ("command_ui_inspect", "Read the currently open command panel, a popup (scope='dialog:0'), or a docked pane "
     "(scope='pane:Layer Manager', 'pane:Properties', 'pane:Project Explorer', ...): fields, values, options, status "
     "messages, buttons, grids, any open popups, and the list of panes.",
     obj({"scope": {"type": "string", "description": "'command' (default), 'dialog:<index>' or 'pane:<title>'."},
          "include_hidden": {"type": "boolean", "default": False}, "include_text": {"type": "boolean", "default": True}}),
     t_command_ui_inspect, {"readOnlyHint": True}),
    # command_ui_fill -> t_command_ui_fill: idle wait, field-order guard, command_ui.fill, settle pause, ui_after
    ("command_ui_fill", "Fill fields in the open command panel like a user (types the value, then tabs out so TBC "
     "validates it), optionally press a button (e.g. 'Add', 'Apply', 'OK') afterwards. Returns each field's value as "
     "TBC now shows it plus what happened after the press (popups, status messages). Verify results with read tools.",
     obj({"values": FIELD_VALUES, "press": {"type": "string", "description": "Button text or id to press after filling."},
          "scope": {"type": "string"}, "stop_on_error": {"type": "boolean", "default": True},
          "wait_seconds": {"type": "number", "default": 1.0}}, ["values"]),
     t_command_ui_fill, {"readOnlyHint": False, "destructiveHint": True}),
    # command_ui_click -> t_command_ui_click: idle wait, asynchronous press inside TBC, ui_after
    ("command_ui_click", "Press a button in the open command panel (or a popup with scope='dialog:0'), then report "
     "popups/status.",
     obj({"button": {"type": "string"}, "scope": {"type": "string"}, "wait_seconds": {"type": "number", "default": 1.0}},
         ["button"]),
     t_command_ui_click, {"readOnlyHint": False, "destructiveHint": True}),
    # tbc_view -> t_view: ipy/view.py; screenshot refused when another app covers the view (privacy); the PNG is
    # attached to the result by handle(). Not read-only because set_extents moves the user's view.
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
    # ui_grid -> t_ui_grid: command_ui grid_read / grid_set / grid_click (checkboxes are toggled by a real click)
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
    # command_ui_close -> command_ui.close directly (CloseCommand / CloseAll on TBC's command host); no idle wait
    ("command_ui_close", "Close the open command panel (all=true closes every open command).",
     obj({"all": {"type": "boolean", "default": False}}),
     lambda a: run_ipy("command_ui", "close", a), {"readOnlyHint": False, "destructiveHint": False}),
    # tbc_dialogs -> t_tbc_dialogs: TBC popups (command_ui) and standard Windows dialogs (native_dialogs, Win32
    # from this process); safe_dismiss for action=dismiss; non-cancel buttons refused while a license popup is open
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
    # --- Knowledge (local files; TBC only for the license flags, the release stamp and script runs) ---
    # tbc_skills -> t_skills: knowledge.py skills + license annotations
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
    # tbc_script -> t_script: saved scripts; save compile-checks in TBC's IronPython, run executes in TBC
    # (mode=write as one undo step). destructiveHint because a run can change the project.
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
    # --- Import / export (Home tab panes, driven through ipy/import_export.py + command_ui) ---
    # tbc_export -> t_export: writes a file on disk; the Export pane is closed again in every case
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
    # tbc_import -> t_import: scan is harmless; import needs confirm=true. allow_cad is accepted but not used by
    # the handler (kept so older callers' arguments still validate).
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
    # --- Timing ---
    # tbc_wait_idle -> wait_idle directly; returns {"idle_after_s": seconds waited}
    ("tbc_wait_idle", "Wait until TBC has finished computing (Compute Project / progress windows gone and the project "
     "is not recalculating). The command tools already do this; call it after other changes before reading results.",
     obj({"timeout": {"type": "number", "default": 900}}),
     lambda a: {"idle_after_s": wait_idle(a.get("timeout"))}, {"readOnlyHint": True}),
    # --- License and help ---
    # tbc_license -> t_license: profile in %LOCALAPPDATA%\TBC-MCP\license (private, never in the repo); check is live
    ("tbc_license", "What THIS user's TBC license allows (users have different licenses/subscriptions). "
     "action=summary: licensed features with expiry dates, subscription/maintenance dates, and how many commands are "
     "available - built automatically the first time a TBC session is seen and refreshed when the license changes. "
     "action=check keys=[...]: live check of specific commands. action=unlicensed (contains=...): commands not "
     "available. action=refresh: rebuild now. Commands are also checked live before every run.",
     obj({"action": {"type": "string", "enum": ["summary", "check", "unlicensed", "refresh"], "default": "summary"},
          "keys": {"type": "array", "items": {"type": "string"}}, "contains": {"type": "string"},
          "limit": {"type": "integer", "default": 200}}),
     t_license, {"readOnlyHint": True}),
    # tbc_help -> t_help: tbc_help.py over the installed HTML help; TBC is asked only to map a command key to its topic
    ("tbc_help", "TBC's own installed help (offline, ~3,500 topics). action=search finds topics by words; action=read "
     "returns a topic's text by topic number, or by command key (command='adjustprojectterranet') via the command's "
     "help topic. Read a command's help before using an unfamiliar command - it says what the command does, whether "
     "it acts immediately, and its options.",
     obj({"action": {"type": "string", "enum": ["search", "read"], "default": "search"},
          "query": {"type": "string"}, "topic": {"type": "string"}, "command": {"type": "string"},
          "limit": {"type": "integer", "default": 15}, "max_chars": {"type": "integer", "default": 6000}}),
     t_help, {"readOnlyHint": True}),
    # --- The user's rules and memory (local files only) ---
    # tbc_preferences -> t_preferences: knowledge/preferences.json, appended to INSTRUCTIONS at initialize
    ("tbc_preferences", "The user's standing rules (how they want things done in TBC). They are sent to every AI "
     "in this server's instructions, so they apply in every chat. action=add when the user states a lasting "
     "preference ('always...', 'from now on...', 'I want...'); update/remove when they change their mind; list to "
     "review. Use tbc_memory for facts about TBC, tbc_project_notes for one job's rules, this tool for the user's "
     "general wishes. The same preference is never stored twice. Ask before adding or changing.",
     obj({"action": {"type": "string", "enum": ["list", "add", "update", "remove"], "default": "list"},
          "text": {"type": "string"}, "topic": {"type": "string"}, "id": {"type": "integer"}}),
     t_preferences, {"readOnlyHint": False, "destructiveHint": False}),
    # tbc_memory -> t_memory: knowledge/memory/lessons.jsonl; a lesson with DANGER_WORDS gates its command behind
    # confirm=true (check_known_danger)
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
    # tbc_project_notes -> t_project_notes: projects.py, the job knowledge base shared with Civil 3D MCP and Project
    # Analyzer (CIVIL3D_KNOWLEDGE_DIR). The description embeds P.REFERENCE_FORMATS; tests/test_project_knowledge.py
    # checks its wording. TBC is only asked for the open project's path.
    ("tbc_project_notes", "Notes about ONE job, in the project knowledge base SHARED with Civil 3D MCP and Project "
     "Analyzer (same files: what one tool learns about a job, the others see). For facts that only matter on this job: "
     "what its layers, point ranges, surfaces and codes are for, control and datum, which survey belongs to which "
     "feature, the client's standards, decisions the user made. A job is matched by folder: the open .vce belongs to "
     "the job whose linked folder contains it; its notes come back with project_info and the first code or panel "
     "result of a session, each with 'by' (tbc, civil3d or project-analyzer). "
     "action=list (the open project's job, or project); link (project, optional folder; default the open .vce's "
     "folder) creates a job or adds a folder to one - link to the existing name when Civil 3D or the analyzer already "
     "know the job; unlink (project, folder) drops a folder TBC linked; add (note) / update (id, note) / remove (id), "
     "optional project - only notes TBC wrote can be updated or removed, correct another tool's note by adding one. "
     "WRITING A NOTE: one fact, one line, in the suite's reference formats so Project Analyzer ties it to the same "
     "items in documents and drawings: " + P.REFERENCE_FORMATS + ". End it with [source: <TBC project file name or "
     "command>] when there is one, e.g. '[source: Elm Street.vce]'. Never put license details, licensee or company "
     "names from the TBC license, user-profile paths or tokens in a note (they are refused). "
     "files lists the job's files folder: reference files the user drops in, and Project Analyzer's reports - "
     "analysis\\ (OVERVIEW.md, TIMELINE.md, PEOPLE.md, ISSUES.md, INDEX.md) and analysis\\intel\\ (CHECKS.md: "
     "problems to follow up - conflicting amounts, unanswered RFIs, missing documents, date conflicts, versions after "
     "FINAL - under Needs attention / Worth checking / For information; STORIES.md: each RFI, change order and "
     "submittal from first mention to last, with people and amounts; ENTITIES.md: every person, organization, place, "
     "document number, structure, station and sheet with its aliases and the files it appears in; TIMELINE.md "
     "automatic timeline; THREADS.md email conversations; VERSIONS.md document versions and what changed; AMOUNTS.md), "
     "plus graph.html / timeline.html, interactive pages for the user to open in a browser (read returns their path, "
     "not their HTML). read (file) returns a text file from it. Use them: the user asks about an RFI, change order or "
     "submittal -> read its story in STORIES.md; about a structure (MH-3), station (12+50) or sheet (C-104) -> look "
     "it up in ENTITIES.md for the documents that mention it; before relying on an amount, revision or sheet that "
     "might be in dispute -> check CHECKS.md. The first result of a session lists the job's 'Needs attention' items. "
     "COPIED FOLDERS: a job folder is usually a copy of a project from another drive or server, so paths written in "
     "its files - a TBC project's imported files, linked images and data sources - point at the original location. "
     "locate (path, as TBC or a file shows it) says where that file is in the copy: Project Analyzer's relink_map.csv "
     "first, then its list of original locations, then a check on disk; it returns the status (found, found by name, "
     "ambiguous, missing, translated, not known), the absolute path and the path relative to the copy's top folder, "
     "and for a missing file where it should be. When TBC reports a missing or unresolved file, or a path the user "
     "mentions doesn't exist, use locate BEFORE telling the user it's missing (and an existing path isn't necessarily "
     "the right file). 'not known' means ask the user where the original folder was - never guess. REFERENCES.md and "
     "relink_map.csv in analysis\\intel\\ list the job's missing files. When you find or fix a reference (e.g. the "
     "user relinks an imported file), offer to record it as a note, e.g. 'Imported file P:\\Jobs\\1234\\Survey\\CP.job "
     "is Project\\Survey\\CP.job in the copy [source: TBC project Elm.vce]'. "
     "Kept only on this computer. Ask the user before adding or changing.",
     obj({"action": {"type": "string", "enum": ["list", "link", "unlink", "add", "update", "remove", "files", "read", "locate"], "default": "list"},
          "path": {"type": "string", "description": "locate: a file path as TBC or a file shows it (the original location)."},
          "project": {"type": "string", "description": "Job name; omit to use the job the open TBC project belongs to."},
          "folder": {"type": "string"}, "note": {"type": "string"},
          "id": {"type": "string", "description": "Note id, e.g. 'note-3'."},
          "file": {"type": "string", "description": "read: path inside the files folder, as listed by action=files."},
          "max_chars": {"type": "integer", "default": P.MAX_READ_CHARS}}),
     t_project_notes, {"readOnlyHint": False, "destructiveHint": False}),
]

# --- Power tool ---
# execute_python -> t_execute_python: arbitrary IronPython inside TBC (bridge h_execute_python, which provides the
# predefined names listed in the description). Only registered when TBC_MCP_ALLOW_PYTHON is not "0"; note that the
# server itself still uses the bridge's execute_python internally (run_ipy, the *_CODE snippets) either way.
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

# name -> tool tuple, for tools/call dispatch in handle()
TOOL_MAP = {t[0]: t for t in TOOLS}

# Server instructions sent to the client in the initialize answer (handle() appends the user's preferences from
# K.prefs_text()). This is the AI's first briefing: where to start (working_safely_in_tbc, tbc_license), the
# workflow, the two knowledge scopes (general TBC knowledge vs. one job's shared notes), tidiness, license
# popups and the add-never-delete rule for TBC versions. Keep it in step with README and working_safely_in_tbc.
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
    "files folder under analysis\\ (tbc_project_notes action=files / read): in analysis\\intel\\, STORIES.md tells "
    "the story of each RFI, change order and submittal, ENTITIES.md says which documents mention a structure, "
    "station or sheet, and CHECKS.md lists open problems - check it before relying on an amount, revision or sheet "
    "that might be in dispute, and mention its 'Needs attention' items when they bear on the task. Job folders are "
    "usually COPIES of a project from elsewhere: when TBC reports a missing or unresolved file (imported file, linked "
    "image or data source) or a path the user gives doesn't exist, run tbc_project_notes action=locate (path) before "
    "saying it's missing, and never guess where a file went. Write project notes in the suite's reference formats "
    "(2026-10-03, 12+50, MH-3, C-104, RFI 12, CO 4, $12,500.00, John Smith (J. Smith)), ending with [source: <TBC "
    "project or command>] when there is one. Never put license details, licensee/company names, user-profile paths "
    "or tokens in shared notes.\n"
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
# MCP's stdio transport: newline-delimited JSON-RPC 2.0 messages, requests on stdin, responses on stdout.
# Nothing else may be printed to stdout (log() writes to stderr).
def send(msg):
    """Write one JSON-RPC message to stdout as a single line and flush at once (the client waits for it).

    ensure_ascii=False keeps non-ASCII text readable; main() switches stdout to UTF-8 with "\\n" newlines so
    Windows does not turn the line end into CRLF or use a legacy code page.
    """
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def result_text(value):
    """Text for a tool result's content block: strings as they are (e.g. search_sdk_docs, a skill's markdown),
    everything else as indented JSON (indent=1: readable for the AI without wasting many characters)."""
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=1, ensure_ascii=False)


def handle(msg):
    """Answer one decoded JSON-RPC message; returns the "result" value (None for notifications).

    initialize -> protocol version (the client's if supported, else the newest in SUPPORTED_PROTOCOLS),
                  capabilities (tools only; the list never changes at runtime), serverInfo, and INSTRUCTIONS
                  followed by the user's preferences.
    ping       -> {}.
    tools/list -> every TOOLS entry as {name, description, inputSchema, annotations}.
    tools/call -> runs the handler with the call's arguments. The result becomes one text content block
                  (result_text) plus, when the result dict has "_image_path", an image block with that PNG
                  base64-encoded. BridgeError / K.KnowledgeError -> isError result with the message; any other
                  exception -> isError result "<Type>: <message>". Tool failures are therefore results, not
                  JSON-RPC errors, so the AI sees and can react to them.
    resources/list, prompts/list -> empty lists (this server offers neither).
    Raises RpcError for an unknown tool (-32602, invalid params) or an unknown method (-32601).
    Messages without an id are notifications (e.g. notifications/initialized) and get no answer.
    """
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}
    if mid is None:  # notification
        return None
    if method == "initialize":
        pv = params.get("protocolVersion")
        # Read the preferences on every initialize, so a rule added in one chat reaches the next chat's AI
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
            # t[3] = the handler. Runs synchronously on this (only) request thread: while a tool waits for TBC
            # (e.g. wait_idle, up to TBC_MCP_IDLE_TIMEOUT) no other message is read.
            value = t[3](params.get("arguments") or {})
            # Internal key, not part of the text result: the PNG to attach (tbc_view screenshot)
            img = value.pop("_image_path", None) if isinstance(value, dict) else None
            content = [{"type": "text", "text": result_text(value)}]
            if img:
                import base64
                with open(img, "rb") as f:
                    content.append({"type": "image", "mimeType": "image/png", "data": base64.b64encode(f.read()).decode("ascii")})
            return {"content": content, "isError": False}
        except (BridgeError, K.KnowledgeError) as ex:
            # Expected failures: the message was written for the AI (and often tells it what to do next)
            return {"content": [{"type": "text", "text": str(ex)}], "isError": True}
        except Exception as ex:
            # Anything else (KeyError for a missing argument, ValueError, OSError ...): still a tool error, not a
            # protocol error, so the server keeps running and the AI sees what went wrong
            return {"content": [{"type": "text", "text": "%s: %s" % (type(ex).__name__, ex)}], "isError": True}
    if method in ("resources/list", "prompts/list"):
        return {method.split("/")[0]: []}  # {"resources": []} / {"prompts": []}
    raise RpcError(-32601, "Method not found: %s" % method)


class RpcError(Exception):
    """A JSON-RPC protocol error (unknown method or tool). main() sends it as {"error": {"code", "message"}};
    standard codes: -32601 method not found, -32602 invalid params, -32603 internal error, -32700 parse error.
    Tool failures are NOT RpcErrors: handle() returns them as isError results."""
    def __init__(self, code, message):
        """code: JSON-RPC error code (int); message: text sent to the client."""
        Exception.__init__(self, message)
        self.code = code


def watch_tbc(poll=2.0):
    """Exit this MCP server once the TBC process it was bridging to has gone away (closed or crashed).
    Waits patiently until TBC has been seen at least once, so starting the server before TBC is fine.

    poll: seconds between checks (2 s; tests/test_watchdog.py expects an exit within 10 s of TBC dying).
    Runs forever on the daemon thread started by main(). Each pass reads the info file: a live pid there is
    remembered as "TBC seen". Once a remembered pid is no longer alive, it deletes the info file if it still
    names that pid (a crashed TBC cannot delete it itself) and ends the whole process with os._exit(0)
    (sys.exit in a thread would only end the thread, and the main thread is blocked reading stdin).
    A bridge merely switched off (info file deleted) while TBC keeps running does not end the server.
    """
    import time  # (already imported at module level; harmless)
    seen_pid = None
    while True:
        time.sleep(poll)
        info = read_info()
        pid = info.get("pid") if info else None
        if pid and pid_alive(pid):
            seen_pid = pid  # follows a TBC restart too: the newest live pid is the one watched
        elif seen_pid and not pid_alive(seen_pid):
            log("TBC (pid %s) has exited; shutting down MCP server." % seen_pid)
            if info and info.get("pid") == seen_pid:
                try:
                    os.remove(INFO_FILE)
                except OSError:
                    pass
            os._exit(0)


def main():
    """Entry point: start the watchdog, then serve JSON-RPC messages from stdin until the client closes it.

    The watchdog is skipped when TBC_MCP_EXIT_WITH_TBC=0 or for a manual TBC_MCP_PORT connection (no info
    file / pid to watch). stdin/stdout are switched to UTF-8 with "\\n" line ends (instead of Windows' default
    code page and CRLF translation). Each non-empty input line is one message:
    invalid JSON -> parse error (-32700); requests get {"result": ...} or {"error": ...}; notifications get
    nothing. Messages are handled one at a time, in order.
    """
    if EXIT_WITH_TBC and not os.environ.get("TBC_MCP_PORT"):
        import threading
        # daemon=True: the thread never keeps the process alive after stdin closes and main() returns
        threading.Thread(target=watch_tbc, name="tbc-watchdog", daemon=True).start()
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    except Exception:
        pass  # streams without reconfigure() are used as they are
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
            if msg.get("id") is not None:  # notifications are never answered
                send({"jsonrpc": "2.0", "id": msg["id"], "result": res})
        except RpcError as ex:
            send({"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": ex.code, "message": str(ex)}})
        except Exception as ex:
            # Unexpected errors inside handle() itself become a JSON-RPC internal error (-32603)
            send({"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": str(ex)}})


if __name__ == "__main__":
    main()
