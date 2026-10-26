# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
TBC MCP Bridge macro.

Runs inside Trimble Business Center (IronPython 3.4) and exposes the open
project over a localhost TCP socket so an external MCP server
(mcp_server/tbc_mcp_server.py) can drive it. TBC has no general automation
API for outside programs, so this macro is the only way in: everything the MCP
server does to TBC ends up as a request handled here.

NOTE: keep this file IronPython 3.4 compatible (no f-strings, no annotations).

Install and start
-----------------
- install_macro.ps1 (needs admin) copies this file to
  C:\\ProgramData\\Trimble\\MacroCommands3\\MCP, creates the MCP.dict macro
  cache there and lets normal users write that folder. After a TBC restart the
  macro appears as Macros > MCP > "MCP Bridge".
- TBC calls Setup() when it registers the macro (ribbon caption, tooltip,
  icon) and Execute() each time the button is clicked.
- Click once to start the bridge, click again to stop it. If the bridge died
  on its own, the next click starts a fresh one instead of only stopping.

Wire protocol (one JSON object per line, UTF-8 without BOM, over 127.0.0.1)
---------------------------------------------------------------------------
  request : {"id": 1, "token": "...", "method": "ping", "params": {}}
  response: {"id": 1, "ok": true, "result": ...}
            {"id": 1, "ok": false, "error": "...", "traceback": "..."}
- "method" names a TbcHandlers.h_<method> function; "params" is passed to it
  as a dict ({} when missing or null).
- "token" must equal this session's token or the reply is
  {"ok": false, "error": "invalid token"} and nothing runs.
- Unknown methods reply "unknown method: <name>". Exceptions inside a handler
  reply ok=false with "Type: message" and the IronPython traceback.
- A connection may carry several request lines; each gets one reply line.
  The MCP server's call_bridge() opens one connection per request.

Connection info file
--------------------
%TEMP%\\tbc_mcp_bridge.json (System.IO.Path.GetTempPath()) holds
  {"port": 47821, "token": "<32 hex chars>", "pid": <TBC process id>,
   "version": BRIDGE_VERSION, "started": "<ISO 8601 local time>"}
The server's bridge_endpoint() reads it; the token is a fresh GUID on every
start, so only processes that can read this user's %TEMP% can connect. The
pid lets the server notice a crashed TBC (stale file) and its watch_tbc()
watchdog exit when TBC goes away. The file is deleted when the bridge stops
or TBC exits normally. A log of bridge events goes to %TEMP%\\tbc_mcp_bridge.log.

Threading
---------
- Execute() runs on TBC's UI thread; it captures Dispatcher.CurrentDispatcher
  (the UI dispatcher) for the server.
- One background accept thread takes connections; each connection gets its
  own background thread that reads lines and writes replies.
- The TBC model must not be touched from those socket threads, so every
  handler call is marshalled onto the UI thread with Dispatcher.Invoke at
  DispatcherPriority.Background (runs when TBC's UI thread has nothing more
  important to do, so it does not cut into TBC's own redraw work). Invoke is
  synchronous: the socket thread waits for the result.
- Handlers marked @async_ui (only run_command) are queued with BeginInvoke and
  answered at once with {"queued": true}: TBC commands may open panels or
  modal dialogs that would otherwise block the reply.
- Without a dispatcher (test harness outside TBC, tests/dev/ipy_bridge_harness.py)
  handlers run directly on the socket thread.

Handlers (TbcHandlers.h_*; lengths/coordinates in display units unless
params "units" == "meters"; TBC stores everything in meters internally)
-------------------------------------------------------------------------
  ping              -> {pong, bridge_version, in_tbc, import_errors}
  project_info      -> name, path, description, dates, units factor, counts
  list_entities     type_contains, layer, name_contains, graphical_only,
                    limit (200), offset -> {total_matched, returned, offset,
                    counts_by_type, entities:[{serial,type,name,layer}]}
  get_entity        serial, property_filter, units -> summary + every readable
                    .NET property + "vertices" (up to 2000) for element lists
  list_points       name_contains, layer, limit (500), offset, units ->
                    {units, total_matched, returned, points:[{serial, name,
                    layer, feature_code, easting, northing, elevation}]}
  list_layers       with_counts (True) -> {layers:[{serial, name, visible,
                    locked, color, member_count}]}
  list_surfaces     units -> {units, surfaces:[{serial, name, layer,
                    vertices, triangles, min_elevation, max_elevation}]}
  surface_elevation surface (serial or name), points [{x, y}], units ->
                    {surface, units, results:[{x, y, z, on_surface}]}
  get_selection     limit (500) -> {count, entities}
  set_selection     serials -> {selected}   ([] clears the selection)
  list_commands     contains, limit (300) -> {count, commands:[{key, caption}]}
  create_points     points [{name, easting, northing, elevation?, layer?}],
                    units -> {created, points:[{serial, name}]}   (one undo step)
  create_linestring vertices [{x, y, z?}] (>= 2), closed, name, layer, units
                    -> {serial, name, vertices}                  (one undo step)
  create_layer      name, color ("#RRGGBB") -> {serial, name}    (one undo step)
  set_properties    serial or serials, properties {Name: value} ->
                    {updated, properties}                        (one undo step)
  delete_entities   serials -> {deleted}  (removes from the container in code;
                    the MCP tool of that name uses TBC's Delete command instead)
  save_project      -> {saved}
  run_command       key, args -> {queued: true}  (async, see Threading)
  execute_python    code, transaction (True) -> {stdout, result}

execute_python
--------------
Runs arbitrary IronPython on the UI thread with a fresh namespace (clr,
project/prj, wv, bridge = the TbcHandlers instance, jsonable, result, and the
TBC types imported below). The code reports back by assigning `result`
(converted with jsonable, depth 3) and by printing (last 20000 characters of
stdout are returned). With transaction=True (the default) and a project open,
the code runs inside transact(): one "MCP: python" undo step that rolls back
if the code raises. The server's run_ipy() uses this to send the helper
modules in mcp_server/ipy/ (with transaction=False by default).

Ribbon light
------------
The button shows a green (ON) or red (OFF) dot drawn in code (_status_icon).
TBC saves the ribbon appearance when it exits and restores it at startup,
after macros are set up, so a stale "ON" could come back (for example after a
crash). Three things keep the light honest:
  - _schedule_startup_reset() re-applies OFF once the UI is idle at startup,
  - _install_close_reset() sets OFF when the main window starts closing,
    before TBC saves its ribbon layout,
  - _start_status_monitor() checks every 2 s whether the bridge is really
    listening and recolors the button (and forgets a dead instance).

Shutdown and cleanup
--------------------
BridgeServer.stop() (second click, or AppDomain.ProcessExit when TBC exits
normally) stops the listener, which ends the accept loop, and deletes the info
file. Socket threads are background threads, so they never keep TBC alive.
After a crash the info file stays behind; the server sees its dead pid and
removes it.
"""
import clr
import sys
import json
import math
import traceback

clr.AddReference("System")
clr.AddReference("WindowsBase")       # WPF Dispatcher (System.Windows.Threading)
clr.AddReference("System.Drawing")    # Bitmap for the status light, ColorTranslator for "#RRGGBB" colors
from System import Func, Action, Object, Array, Guid, AppDomain, Environment, DateTime, UInt32
from System.Collections.Generic import List
from System.Threading import Thread, ThreadStart
from System.Net import IPAddress
from System.Net.Sockets import TcpListener
from System.IO import StreamReader, StreamWriter, Path, File, FileInfo
from System.Text import UTF8Encoding
from System.Windows.Threading import Dispatcher, DispatcherPriority
from System.Drawing import Bitmap, ColorTranslator

# execute_python captures print() output in a StringIO; the fallback covers a Python 2 style stdlib.
try:
    from io import StringIO
except ImportError:
    from StringIO import StringIO

# ---------------------------------------------------------------------------
# TBC imports (guarded so the socket core can be tested outside TBC)
# ---------------------------------------------------------------------------
# IN_TBC is False when the core TBC types can't be imported (e.g. running under TBC's ipy.exe outside TBC, see
# tests/dev/ipy_bridge_harness.py). _IMPORT_ERRORS collects what failed; ping reports it and Execute shows it to the
# user, so a missing optional feature is visible instead of silently broken.
IN_TBC = True
_IMPORT_ERRORS = []
for _asm in ("Trimble.Sdk.Interfaces", "Trimble.Sdk.Core", "Trimble.Sdk.Geometry", "Trimble.Sdk.Coordinates",
             "Trimble.Sdk.Surface", "Trimble.Sdk.Alignment"):
    try:
        clr.AddReference(_asm)  # TBC preloads these; explicit refs also let tests import them
    except:
        pass
# Core types every handler relies on. Note the namespaces are Trimble.Vce.* even though the assemblies above are
# named Trimble.Sdk.*.
try:
    from Trimble.Vce.Core import TransactMethodCall, GlobalSelection
    from Trimble.Vce.Core.Components import WorldView, Project, Layer
    from Trimble.Vce.Interfaces import Client
    from Trimble.Vce.Interfaces.SnapIn import IMemberManagement, IRepresentGraphically
    from Trimble.Vce.Interfaces.Units import LinearType
    from Trimble.Vce.Geometry import Point3D
except Exception as ex:
    IN_TBC = False
    _IMPORT_ERRORS.append("core: " + str(ex))

def _opt_import(label, fn):
    """Run one optional import function; return its value, or None (recording the error under `label`).

    Optional types only disable the handlers that need them (those handlers raise "... unavailable"),
    instead of stopping the whole bridge from loading.
    """
    try:
        return fn()
    except Exception as ex:
        _IMPORT_ERRORS.append(label + ": " + str(ex))
        return None

def _imp_point():
    """Import TBC's survey point class (Trimble.Vce.Coordinates.Point), used as TbcPoint."""
    from Trimble.Vce.Coordinates import Point
    return Point

def _imp_model3d():
    """Import Model3D, the class TBC surfaces are (list_surfaces, surface_elevation)."""
    from Trimble.Vce.Gem import Model3D
    return Model3D

def _imp_linestring():
    """Import the linestring types create_linestring needs; returned as one tuple stored in _ls."""
    from Trimble.Vce.Alignment.Linestring import Linestring, ElementFactory, IStraightSegment, IXYZLocation
    return (Linestring, ElementFactory, IStraightSegment, IXYZLocation)

def _imp_office():
    """Import TrimbleOffice, TBC's application object (main window, ribbon, command processor, current project)."""
    clr.AddReference("Trimble.Vce.UI.UIManager")
    from Trimble.Vce.UI.UIManager import TrimbleOffice
    return TrimbleOffice

if IN_TBC:
    TbcPoint = _opt_import("Point", _imp_point)  # named TbcPoint so it doesn't clash with other Point types
    Model3D = _opt_import("Model3D", _imp_model3d)
    _ls = _opt_import("Linestring", _imp_linestring)
    TrimbleOffice = _opt_import("TrimbleOffice", _imp_office)
else:
    TbcPoint = Model3D = _ls = TrimbleOffice = None

BRIDGE_VERSION = "0.2.0"            # reported by ping and written to the info file
DEFAULT_PORT = 47821                # first port tried; BridgeServer.start() tries this and the next 9
INSTANCE_KEY = "TbcMcpBridge.Instance"  # AppDomain slot holding the running BridgeServer (see Execute)
INFO_FILE = Path.Combine(Path.GetTempPath(), "tbc_mcp_bridge.json")  # read by the server's bridge_endpoint()


# ---------------------------------------------------------------------------
# Macro entry points
# ---------------------------------------------------------------------------
# State that must survive between clicks (the running server, the close hook, the status timer) is kept in
# AppDomain.CurrentDomain data slots rather than module globals. The slots are process-wide, so a later
# Setup/Execute call finds them however TBC loads this module.
def Setup(cmdData, macroFileFolder):
    """TBC macro entry point: describe the ribbon button when TBC registers the macro.

    cmdData: TBC's command description object (Key, Caption, tab/group keys, tooltip, images).
    macroFileFolder: folder the macro was loaded from (unused).
    Side effects: sets the button image to the current light state and, if the bridge is not running,
    schedules the startup reset of the light (see _schedule_startup_reset).
    """
    # Key / CommandName are what _update_ribbon looks the tool up by (AppToolbar.Tools["TbcMcpBridge"]).
    cmdData.Key = "TbcMcpBridge"
    cmdData.CommandName = "TbcMcpBridge"
    cmdData.Caption = "_MCP Bridge (start/stop)"
    # Each optional property is set in a try: if a TBC release lacks one, the macro still registers.
    try:
        cmdData.DefaultTabKey = "Macros"       # Macros tab ...
        cmdData.DefaultTabGroupKey = "MCP"     # ... MCP group (matches the MacroCommands3\MCP install folder)
        cmdData.ShortCaption = "MCP Bridge OFF"
        cmdData.Version = 0.1
        cmdData.MacroAuthor = "TBC MCP"
        cmdData.ToolTipTitle = "MCP Bridge"
        cmdData.ToolTipTextFormatted = "Start or stop the local bridge that lets an AI assistant (MCP) work with this project."
    except:
        pass
    try:
        cmdData.EnableNoProject = True  # keep the button usable when no project is open
    except:
        pass
    # Status light: red at startup (bridge not running); Execute switches it to green/red.
    running = AppDomain.CurrentDomain.GetData(INSTANCE_KEY) is not None
    try:
        cmdData.ImageSmall = _status_icon(16, running)
        cmdData.ImageLarge = _status_icon(32, running)
    except:
        pass
    _log("setup (bridge running=%s)" % running)
    if not running:
        # TBC restores the ribbon layout it saved at last exit (which may say ON, e.g. after a
        # crash) *after* macros are set up, so re-apply OFF once the UI is idle.
        _schedule_startup_reset()


def Execute(cmd, currentProject, macroFileFolder, parameters):
    """TBC macro entry point: the ribbon button was clicked. Toggles the bridge.

    Runs on TBC's UI thread. currentProject is kept as a fallback project for TbcHandlers (the handlers
    prefer whatever project is current at call time). cmd, macroFileFolder and parameters are unused.
    - Bridge running and alive: stop it, light OFF, tell the user.
    - Bridge instance present but dead (it stopped on its own): clean it up and start a new one.
    - No bridge: start one, light ON, hook window-close and the 2 s status monitor, show the port
      (and any optional import that failed).
    """
    existing = AppDomain.CurrentDomain.GetData(INSTANCE_KEY)
    if existing is not None:
        alive = _bridge_actually_running()
        try:
            existing.stop()
        except:
            pass
        AppDomain.CurrentDomain.SetData(INSTANCE_KEY, None)
        if alive:
            _update_ribbon(False)
            _log("bridge stopped by user")
            _message("MCP bridge stopped.")
            return
        # it had died on its own: fall through and start a fresh one
    # Dispatcher.CurrentDispatcher here is the UI thread's dispatcher, because Execute runs on the UI thread.
    # The server uses it to run every request on this thread.
    server = BridgeServer(TbcHandlers(currentProject), Dispatcher.CurrentDispatcher)
    port = server.start()
    AppDomain.CurrentDomain.SetData(INSTANCE_KEY, server)
    _update_ribbon(True, port)
    _install_close_reset()
    _start_status_monitor()
    _log("bridge started on port %d" % port)
    msg = "MCP bridge running on 127.0.0.1:" + str(port) + "\n\nClick the macro again to stop it."
    if _IMPORT_ERRORS:
        msg += "\n\nSome features unavailable:\n" + "\n".join(_IMPORT_ERRORS)
    _message(msg)


# ---------------------------------------------------------------------------
# Ribbon status light, log file and user messages
# ---------------------------------------------------------------------------
def _status_icon(size, running):
    """Green (running) or red (stopped) dot used as the ribbon button image.

    size: bitmap width/height in pixels (16 for the small image, 32 for the large one).
    Returns a new System.Drawing.Bitmap (drawn in code, so the macro needs no image files).
    """
    from System.Drawing import Graphics, Color, SolidBrush, Pen, Rectangle
    from System.Drawing.Drawing2D import SmoothingMode
    bmp = Bitmap(size, size)
    g = Graphics.FromImage(bmp)
    try:
        g.SmoothingMode = SmoothingMode.AntiAlias
        fill = Color.FromArgb(40, 200, 70) if running else Color.FromArgb(225, 45, 45)
        edge = Color.FromArgb(20, 110, 40) if running else Color.FromArgb(130, 20, 20)
        m = max(1, size // 8)      # margin around the dot
        d = size - 2 * m - 1       # dot diameter
        g.FillEllipse(SolidBrush(fill), Rectangle(m, m, d, d))
        g.DrawEllipse(Pen(edge, max(1.0, size / 16.0)), Rectangle(m, m, d, d))
        # small semi-transparent white ellipse in the upper left: a highlight so the dot reads as a light
        g.FillEllipse(SolidBrush(Color.FromArgb(150, 255, 255, 255)), Rectangle(m + d // 4, m + d // 6, d // 3, d // 4))
    finally:
        g.Dispose()
    return bmp


LOG_FILE = Path.Combine(Path.GetTempPath(), "tbc_mcp_bridge.log")


def _log(text):
    """Append a timestamped line to %TEMP%\\tbc_mcp_bridge.log. Never raises.

    The log is deleted and started over once it passes about 200 KB, so it can't grow without bound.
    """
    try:
        if File.Exists(LOG_FILE) and FileInfo(LOG_FILE).Length > 200000:
            File.Delete(LOG_FILE)
        File.AppendAllText(LOG_FILE, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + text + "\r\n")
    except:
        pass


def _install_close_reset():
    """Set the light back to OFF when TBC's main window starts closing, before TBC saves its ribbon layout.

    Hooks TrimbleOffice.TheOffice.MainForm.FormClosing once per process (the handler is remembered in the
    "TbcMcpBridge.CloseHook" AppDomain slot so repeated starts don't add it again). Failures are only logged.
    """
    if AppDomain.CurrentDomain.GetData("TbcMcpBridge.CloseHook") is not None:
        return
    try:
        def on_closing(sender, e):
            """FormClosing handler: show OFF so the layout TBC saves on exit doesn't say ON."""
            _update_ribbon(False)
            _log("main window closing -> light OFF")
        TrimbleOffice.TheOffice.MainForm.FormClosing += on_closing
        AppDomain.CurrentDomain.SetData("TbcMcpBridge.CloseHook", on_closing)
    except Exception as ex:
        _log("could not hook FormClosing: " + _err_text(ex))


def _bridge_actually_running():
    """True if the BridgeServer stored in the AppDomain slot exists and is really listening (see is_alive)."""
    srv = AppDomain.CurrentDomain.GetData(INSTANCE_KEY)
    if srv is None:
        return False
    try:
        return bool(srv.is_alive())
    except:
        return False


def _start_status_monitor():
    """Every 2 s (on the UI thread) make the light match whether the bridge is really listening.

    Uses a System.Windows.Forms.Timer, whose Tick runs on the UI thread, so the ribbon can be changed
    directly. Started once per process (the timer is kept in the "TbcMcpBridge.Monitor" AppDomain slot, which
    is also the started-already flag). The ribbon is only touched when the state changes.
    """
    if AppDomain.CurrentDomain.GetData("TbcMcpBridge.Monitor") is not None:
        return
    try:
        clr.AddReference("System.Windows.Forms")
        from System.Windows.Forms import Timer
        state = {"shown": None}  # last state successfully shown on the button (None = not yet known)
        def tick(sender, e):
            """Timer tick: recolor the button if the real bridge state differs from what it shows."""
            alive = _bridge_actually_running()
            if alive != state["shown"]:
                srv = AppDomain.CurrentDomain.GetData(INSTANCE_KEY)
                if not alive and srv is not None:
                    # bridge died on its own: drop the dead instance so the next click starts fresh
                    AppDomain.CurrentDomain.SetData(INSTANCE_KEY, None)
                    _log("bridge no longer listening -> light OFF")
                # Only remember the new state if the ribbon update worked, so a failed update is retried next tick.
                if _update_ribbon(alive, getattr(srv, "port", None)):
                    state["shown"] = alive
        t = Timer()
        t.Interval = 2000  # milliseconds
        t.Tick += tick
        t.Start()
        AppDomain.CurrentDomain.SetData("TbcMcpBridge.Monitor", t)
    except Exception as ex:
        _log("could not start status monitor: " + _err_text(ex))


def _schedule_startup_reset(tries=[0]):
    """At TBC startup, keep re-applying the OFF light until the ribbon tool exists, then start the monitors.

    TBC restores its saved ribbon layout after macros are set up, and the tool may not exist yet when Setup
    runs, so each attempt is queued on the UI dispatcher at ApplicationIdle priority (after TBC's own pending
    work) and retried up to 200 times. Stops early if the user has started the bridge in the meantime.
    tries: the mutable default list is a deliberate attempt counter shared by the queued attempts.
    """
    try:
        from System.Windows.Threading import DispatcherPriority
        def attempt():
            """One try: set OFF; on success hook window-close and the status monitor, else queue another try."""
            tries[0] += 1
            if AppDomain.CurrentDomain.GetData(INSTANCE_KEY) is not None:
                return
            if _update_ribbon(False):
                _log("startup reset -> light OFF (attempt %d)" % tries[0])
                _install_close_reset()
                _start_status_monitor()
            elif tries[0] < 200:
                Dispatcher.CurrentDispatcher.BeginInvoke(DispatcherPriority.ApplicationIdle, Action(attempt))
            else:
                _log("startup reset gave up: ribbon tool not found")
        Dispatcher.CurrentDispatcher.BeginInvoke(DispatcherPriority.ApplicationIdle, Action(attempt))
    except Exception as ex:
        _log("could not schedule startup reset: " + _err_text(ex))


def _update_ribbon(running, port=None):
    """Recolor the macro's ribbon button (Macros tab > MCP) to show bridge state. Returns True on success.

    running: True for green "MCP Bridge ON", False for red "MCP Bridge OFF".
    port: shown in the tooltip when running.
    The ribbon is an Infragistics UltraToolbarsManager (MainForm.AppToolbar); the tool is found by the Key set in
    Setup and changed through its SharedProps. Returns False (never raises) when TrimbleOffice is unavailable or the
    tool doesn't exist yet; callers use that to retry.
    """
    try:
        tm = TrimbleOffice.TheOffice.MainForm.AppToolbar
        sp = tm.Tools["TbcMcpBridge"].SharedProps
        sp.AppearancesSmall.Appearance.Image = _status_icon(16, running)
        sp.AppearancesLarge.Appearance.Image = _status_icon(32, running)
        sp.Caption = "MCP Bridge ON" if running else "MCP Bridge OFF"
        try:
            sp.ToolTipText = ("Running on 127.0.0.1:" + str(port) + ". Click to stop.") if running else "Stopped. Click to start."
        except:
            pass
        return True
    except:
        return False


def _message(text):
    """Show a modal WPF message box titled "TBC MCP Bridge" (only used from Execute, i.e. on a user click). Never raises."""
    try:
        clr.AddReference("PresentationFramework")
        from System.Windows import MessageBox
        MessageBox.Show(text, "TBC MCP Bridge")
    except:
        pass


# ---------------------------------------------------------------------------
# Socket server
# ---------------------------------------------------------------------------
class BridgeServer(object):
    """Token-protected line-delimited JSON server on 127.0.0.1 that dispatches requests to a handler object.

    handlers: object with h_<method>(params) functions (TbcHandlers).
    dispatcher: TBC's UI Dispatcher; requests are run through it. None runs handlers on the socket thread
        (only for the test harness outside TBC).
    port: first port to try (DEFAULT_PORT).
    Attributes: token (fresh 32-hex-digit GUID per instance), port (the port actually bound after start()),
    listener (TcpListener), running (False after stop()), accept_thread.
    """
    def __init__(self, handlers, dispatcher=None, port=DEFAULT_PORT):
        """Store the handler object and dispatcher and make a new session token. Does not open the socket yet."""
        self.handlers = handlers
        self.dispatcher = dispatcher
        self.port = port
        self.token = Guid.NewGuid().ToString("N")  # "N" = 32 hex digits, no dashes
        self.listener = None
        self.running = False

    def start(self):
        """Bind a loopback port, start the accept thread, write the info file. Returns the bound port.

        Tries self.port and the next 9 ports (47821-47830 by default) so a port held by something else, or a
        stale listener, doesn't stop the bridge. Raises if none can be bound. IPAddress.Loopback means only
        this machine can connect.
        """
        last = None
        for p in range(self.port, self.port + 10):
            try:
                l = TcpListener(IPAddress.Loopback, p)
                l.Start()
                self.listener = l
                self.port = p
                break
            except Exception as ex:
                last = ex
        if self.listener is None:
            raise Exception("Could not bind a port: " + str(last))
        self.running = True
        # Background thread: it never keeps the TBC process alive on exit.
        t = Thread(ThreadStart(self._accept_loop))
        t.IsBackground = True
        t.Start()
        self.accept_thread = t
        self._write_info()
        # Clean up the info file when TBC exits normally. After a crash the MCP server
        # notices the dead pid in the info file and shuts itself down.
        try:
            AppDomain.CurrentDomain.ProcessExit += self._on_process_exit
        except:
            pass
        return self.port

    def _on_process_exit(self, sender, args):
        """AppDomain.ProcessExit handler: stop the server (and so delete the info file) when TBC exits normally."""
        self.stop()

    def is_alive(self):
        """True only if the server is actually listening (accept thread alive, listener bound)."""
        try:
            return bool(self.running and self.accept_thread.IsAlive and self.listener.Server.IsBound)
        except:
            return False

    def stop(self):
        """Stop listening and delete the info file. Safe to call more than once; never raises.

        listener.Stop() makes the blocked AcceptTcpClient() in _accept_loop throw, which ends that thread.
        Open client threads end after their current line (they check self.running) or when the client
        disconnects.
        """
        self.running = False
        try:
            self.listener.Stop()
        except:
            pass
        try:
            if File.Exists(INFO_FILE):
                File.Delete(INFO_FILE)
        except:
            pass

    def _write_info(self):
        """Write port, token, TBC pid, bridge version and start time (ISO 8601, "o" format) to INFO_FILE.

        File.WriteAllText writes UTF-8 without a BOM; the server reads it with utf-8-sig, so either works.
        """
        info = {"port": self.port, "token": self.token, "pid": _pid(),
                "version": BRIDGE_VERSION, "started": DateTime.Now.ToString("o")}
        File.WriteAllText(INFO_FILE, json.dumps(info))

    def _accept_loop(self):
        """Accept-thread body: accept connections until stopped, one background thread per connection."""
        while self.running:
            try:
                client = self.listener.AcceptTcpClient()
            except:
                break  # listener stopped (stop()) or broken: end the thread
            # make() binds the current client into the lambda; a bare lambda would see a later loop value.
            def make(c):
                """Return a thread body that serves connection `c`."""
                return lambda: self._serve_client(c)
            t = Thread(ThreadStart(make(client)))
            t.IsBackground = True
            t.Start()

    def _serve_client(self, client):
        """Connection-thread body: read request lines and write one reply line each until EOF or stop.

        UTF8Encoding(False) = UTF-8 without a BOM, so the first reply doesn't start with a BOM (the server
        decodes with utf-8-sig anyway). AutoFlush sends each reply as soon as it's written. Blank lines are
        ignored. Any I/O error just closes the connection.
        """
        try:
            stream = client.GetStream()
            enc = UTF8Encoding(False)
            reader = StreamReader(stream, enc)
            writer = StreamWriter(stream, enc)
            writer.AutoFlush = True
            while self.running:
                line = reader.ReadLine()
                if line is None:
                    break  # client closed the connection
                if not line.strip():
                    continue
                writer.WriteLine(self._handle_line(line))
        except:
            pass
        finally:
            try:
                client.Close()
            except:
                pass

    def _handle_line(self, line):
        """Parse one request line, check the token, run the handler, return the JSON reply line.

        Runs on a connection thread. The handler itself runs on the UI thread via the dispatcher (see the module
        docstring, Threading). Never raises: every failure becomes an ok=false reply carrying the request id
        (None if the line couldn't even be parsed).
        """
        rid = None
        try:
            req = json.loads(line)
            rid = req.get("id")
            # Checked before anything else, so a request without the session token can't run anything.
            if req.get("token") != self.token:
                return json.dumps({"id": rid, "ok": False, "error": "invalid token"})
            method = req.get("method", "")
            params = req.get("params") or {}
            # Only attributes named h_<method> are reachable, so helper methods on TbcHandlers can't be called.
            fn = getattr(self.handlers, "h_" + method, None)
            if fn is None:
                return json.dumps({"id": rid, "ok": False, "error": "unknown method: " + method})
            if getattr(fn, "async_ui", False) and self.dispatcher is not None:
                # fire-and-forget on the UI thread (e.g. commands that open dialogs)
                self.dispatcher.BeginInvoke(DispatcherPriority.Background, Action(lambda: _safe_call(fn, params)))
                return json.dumps({"id": rid, "ok": True, "result": {"queued": True}})
            # `box` carries the result or the error out of work(), which runs on the UI thread. Exceptions are caught
            # inside work() so they come back here as data instead of being raised by Dispatcher.Invoke.
            box = {}
            def work():
                """Run the handler (on the UI thread) and store its result, or the error text and traceback, in box."""
                try:
                    box["result"] = fn(params)
                except Exception as ex:
                    box["error"] = _err_text(ex)
                    box["traceback"] = traceback.format_exc()
                return None
            if self.dispatcher is not None:
                # Background priority: run only when TBC's UI thread has nothing more important to do, instead of
                # the default Send priority, which can cut into TBC's own graphics/redraw work mid-way.
                # Func[Object](work) wraps the Python function in a .NET delegate for Invoke. Invoke blocks this
                # connection thread until work() has finished on the UI thread.
                self.dispatcher.Invoke(DispatcherPriority.Background, Func[Object](work))
            else:
                work()
            if "error" in box:
                return json.dumps({"id": rid, "ok": False, "error": box["error"], "traceback": box.get("traceback")})
            # jsonable() turns .NET values (UInt32, Point3D, enums, collections ...) into JSON-safe Python values.
            return json.dumps({"id": rid, "ok": True, "result": jsonable(box.get("result"))})
        except Exception as ex:
            return json.dumps({"id": rid, "ok": False, "error": _err_text(ex), "traceback": traceback.format_exc()})


# ---------------------------------------------------------------------------
# Small helpers for the server
# ---------------------------------------------------------------------------
def _safe_call(fn, params):
    """Call fn(params) and swallow any error. Used for @async_ui handlers, whose reply was already sent."""
    try:
        fn(params)
    except:
        pass


def _pid():
    """TBC's process id (this macro runs inside TBC's process), or None if it can't be read. Goes into the info file."""
    try:
        from System.Diagnostics import Process
        return Process.GetCurrentProcess().Id
    except:
        return None


def _err_text(ex):
    """Format an exception as "TypeName: message" for error replies and the log."""
    try:
        return type(ex).__name__ + ": " + str(ex)
    except:
        return "error"


def async_ui(fn):
    """Decorator: mark a handler to be queued on the UI thread and answered at once with {"queued": true}.

    _handle_line checks for the attribute. Use it for handlers that may open modal dialogs or long-running TBC
    commands, which would otherwise hold the reply (and the server's socket timeout) hostage.
    """
    fn.async_ui = True
    return fn


# ---------------------------------------------------------------------------
# JSON conversion of .NET values
# ---------------------------------------------------------------------------
# .NET numeric types are matched by Type.Name: IronPython hands some of them over as .NET objects (UInt32 serials,
# for example) that json.dumps can't serialize.
_INT_TYPES = ("Byte", "SByte", "Int16", "UInt16", "Int32", "UInt32", "Int64", "UInt64")
_FLOAT_TYPES = ("Single", "Double", "Decimal")

def jsonable(v, depth=2):
    """Convert a Python or .NET value into something json.dumps accepts.

    v: any value a handler or execute_python code returns.
    depth: how many levels of .NET collections to expand (Python dicts/lists are always expanded, passing
        depth - 1 down); deeper .NET collections and unknown objects become str(v).
    Rules: NaN/infinity -> None (not valid JSON; e.g. the undefined Z of a 2D point); .NET ints/floats/bools ->
    Python ones; enums, Guid, DateTime, TimeSpan, String -> str; Point3D -> {"x","y","z"} (meters, unconverted);
    System.Drawing.Color -> "#RRGGBB"; other .NET enumerables -> list of at most 200 items plus "...".
    """
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, int):
        return v
    if isinstance(v, dict):
        return dict((str(k), jsonable(x, depth - 1)) for k, x in v.items())
    if isinstance(v, (list, tuple)):
        return [jsonable(x, depth - 1) for x in v]
    try:
        t = v.GetType()
    except:
        return str(v)  # not a .NET object
    tn = t.Name
    if tn in _INT_TYPES:
        return int(v)
    if tn in _FLOAT_TYPES:
        return jsonable(float(v))
    if tn == "Boolean":
        return bool(v)
    if t.IsEnum or tn in ("Guid", "DateTime", "TimeSpan", "String"):
        return str(v)
    if tn == "Point3D":
        return {"x": jsonable(float(v.X)), "y": jsonable(float(v.Y)), "z": jsonable(float(v.Z))}
    if tn == "Color":
        return "#%02X%02X%02X" % (v.R, v.G, v.B)
    if depth > 0 and hasattr(v, "__iter__") and tn not in ("String",):
        out = []
        try:
            for i, x in enumerate(v):
                if i >= 200:  # cap so a huge collection can't flood the reply
                    out.append("...")
                    break
                out.append(jsonable(x, depth - 1))
            return out
        except:
            pass  # enumeration failed: fall back to str() below
    return str(v)


def _type_name(o):
    """Full .NET type name of `o` with the "Trimble.Vce." prefix removed (e.g. "Coordinates.Point")."""
    n = o.GetType().FullName
    return n[len("Trimble.Vce."):] if n.startswith("Trimble.Vce.") else n


def _safe(fn, default=None):
    """Return fn(), or `default` if it raises. Used for TBC properties that some object types lack or throw on."""
    try:
        return fn()
    except:
        return default


# ---------------------------------------------------------------------------
# Handlers. Each h_<method>(params) runs on the TBC UI thread.
# ---------------------------------------------------------------------------
class TbcHandlers(object):
    """The bridge's request handlers plus helpers shared with execute_python code (available there as `bridge`).

    Every public method h_<name>(p) answers the wire method <name>; p is the request's params dict and the return
    value becomes the reply's "result" (after jsonable). Raising an exception makes an ok=false reply.
    Units: TBC stores lengths and coordinates in meters. Handlers taking a "units" param accept "display" (default:
    the project's display linear unit, e.g. US survey feet) or "meters", and convert both ways with to_m/from_m.
    Coordinates are x/easting = Point3D.X, y/northing = Point3D.Y, z/elevation = Point3D.Z.
    Writes go through transact(), so each write request is one undo step in TBC (Ctrl+Z reverses it).
    """
    def __init__(self, fallback_project=None):
        """fallback_project: the project TBC passed to Execute; used only when TrimbleOffice can't give the current one."""
        self.fallback_project = fallback_project

    # ----- helpers ---------------------------------------------------------
    def project(self):
        """The core project (Trimble.Vce.Core.Components.Project) of the project open in TBC right now.

        Asked fresh each call (TrimbleOffice.TheOffice.CurrentProject.VceCoreProject) so the bridge follows the user
        when they open another project after starting it. Falls back to the project Execute received.
        Raises "No project is open in TBC" if there is neither.
        """
        if TrimbleOffice is not None:
            try:
                up = TrimbleOffice.TheOffice.CurrentProject
                if up is not None and up.VceCoreProject is not None:
                    return up.VceCoreProject
            except:
                pass
        if self.fallback_project is None:
            raise Exception("No project is open in TBC")
        return self.fallback_project

    def wv(self, prj):
        """The project's WorldView container, which holds the model (fixed serial; see tbc_api_basics)."""
        return prj[Project.FixedSerial.WorldView]

    def factor(self, prj):
        """meters -> display units

        Returns how many display units one meter is (e.g. 3.280833333 for US survey feet, 1.0 for meters), via the
        project's linear unit settings. Multiply meters by it for display values; divide display values by it.
        """
        return float(prj.Units.Linear.Convert(1.0, LinearType.Display))

    def unit_name(self, f):
        """Name the display unit from its meters->display factor `f` (for project_info); "unknown (...)" if no match.

        Matched with a relative tolerance of 1e-6 so the two kinds of foot (survey 3.280833333, international
        3.280839895) stay distinguishable.
        """
        for name, val in (("meter", 1.0), ("US survey foot", 3.280833333), ("international foot", 3.280839895),
                          ("millimeter", 1000.0), ("centimeter", 100.0), ("kilometer", 0.001)):
            if abs(f - val) < 1e-6 * max(1.0, val):
                return name
        return "unknown (factor " + str(f) + " per meter)"

    def to_m(self, prj, val, units):
        """Convert an incoming length/coordinate to meters. units: "meters" (unchanged) or anything else (display). None stays None."""
        if val is None:
            return None
        return float(val) if units == "meters" else float(val) / self.factor(prj)

    def from_m(self, prj, val, units):
        """Convert a value in meters for output. None, non-numbers and NaN/infinity (e.g. no elevation) become None."""
        if val is None:
            return None
        try:
            f = float(val)
        except:
            return None
        if math.isnan(f) or math.isinf(f):
            return None
        return f if units == "meters" else f * self.factor(prj)

    def transact(self, prj, caption, fn):
        """Run fn() as one TBC undo step named `caption` and return its result.

        TBC's pattern for changing the model (tbc_api_basics): AddBeginMark/AddEndMark with Command granularity
        bracket the change so Ctrl+Z undoes it as one step, and the TransactMethodCall guard collects the changes.
        guard.Commit() keeps them; if fn() raises, Commit is never reached and the changes roll back. The end mark
        is added in `finally` so the undo bracket is closed even on error. The exception propagates to the caller.
        """
        prj.TransactionManager.AddBeginMark(Client.CommandGranularity.Command, caption)
        try:
            with TransactMethodCall(prj.TransactionCollector) as guard:
                r = fn()
                guard.Commit()
            return r
        finally:
            prj.TransactionManager.AddEndMark(Client.CommandGranularity.Command)

    def lookup(self, prj, serial):
        """Object with this serial number, via the project's Concordance (serials are UInt32 in .NET). Raises if none."""
        o = prj.Concordance.Lookup(UInt32(int(serial)))
        if o is None:
            raise Exception("No entity with serial " + str(serial))
        return o

    def layer_name(self, prj, serial):
        """Name of the layer with this serial (objects store their layer as a serial), or None."""
        try:
            l = prj.Concordance.Lookup(serial)
            return l.Name if l is not None else None
        except:
            return None

    def layer_serial(self, prj, name_or_serial):
        """Layer serial (UInt32) for an int serial or a layer name.

        A name goes through Layer.FindOrCreateLayer, so a layer that doesn't exist yet is CREATED (callers run this
        inside a transaction). Note a numeric string is treated as a name, not a serial.
        """
        if isinstance(name_or_serial, int):
            return UInt32(name_or_serial)
        return Layer.FindOrCreateLayer(prj, str(name_or_serial)).SerialNumber

    def summarize(self, prj, o):
        """Short description of an object: {"serial", "type", "name"?, "layer"?} (name/layer only when the object has them)."""
        d = {"serial": int(o.SerialNumber), "type": _type_name(o)}
        n = _safe(lambda: o.Name)
        if n is not None:
            d["name"] = str(n)
        ls = _safe(lambda: o.Layer)
        if ls is not None:
            try:
                d["layer"] = self.layer_name(prj, ls)
            except:
                pass
        return d

    def walk(self, container, graphical_only=True, seen=None):
        """Generator over every object in `container` and, recursively, in nested containers.

        graphical_only: yield only objects implementing IRepresentGraphically (things drawn in the views); nested
            containers are still descended into either way.
        seen: set of serials already visited, so an object reachable from two containers is yielded once.
        Containers are recognised by IMemberManagement. clr.GetClrType turns the interface into a .NET Type for
        isinstance (the IronPython form of typeof). Objects without a SerialNumber are skipped.
        """
        if seen is None:
            seen = set()
        mm = clr.GetClrType(IMemberManagement)
        rg = clr.GetClrType(IRepresentGraphically)
        for o in container:
            try:
                s = int(o.SerialNumber)
            except:
                continue
            if s in seen:
                continue
            seen.add(s)
            if not graphical_only or isinstance(o, rg):
                yield o
            if isinstance(o, mm):
                for c in self.walk(o, graphical_only, seen):
                    yield c

    def find_surface(self, prj, ref):
        """Surface (Model3D) by serial (int) or exact name (first match in the WorldView). Raises if not found."""
        if Model3D is None:
            raise Exception("Model3D type unavailable")
        if isinstance(ref, int):
            return self.lookup(prj, ref)
        for o in self.walk(self.wv(prj), False):
            if isinstance(o, Model3D) and str(o.Name) == str(ref):
                return o
        raise Exception("Surface not found: " + str(ref))

    # ----- read ------------------------------------------------------------
    def h_ping(self, p):
        """Health check (works without a project). Returns {pong, bridge_version, in_tbc, import_errors}."""
        return {"pong": True, "bridge_version": BRIDGE_VERSION, "in_tbc": IN_TBC, "import_errors": _IMPORT_ERRORS}

    def h_project_info(self, p):
        """Facts about the open project. No params.

        Returns name, path, description, modified, created, last_saved, vertical_datum, display_linear_unit,
        meters_to_display_factor (see factor), point_count, layer_count, worldview_top_level_count. Each value is
        read with _safe, so one unreadable property gives None instead of failing the call.
        """
        prj = self.project()
        f = self.factor(prj)
        info = {
            # In TBC 2026 Project.FileName is the bare file name and ProjectName the full path
            "name": _safe(lambda: Path.GetFileNameWithoutExtension(str(prj.FileName))),
            "path": _safe(lambda: str(prj.ProjectName)),
            "description": _safe(lambda: str(prj.Description)),
            "modified": _safe(lambda: bool(prj.Modified)),
            "created": _safe(lambda: str(prj.Created)),
            "last_saved": _safe(lambda: str(prj.LastSaved)),
            "vertical_datum": _safe(lambda: str(prj.VerticalDatum)),
            "display_linear_unit": self.unit_name(f),
            "meters_to_display_factor": f,
            "point_count": _safe(lambda: len(TbcPoint.GetAllPoints(prj))) if TbcPoint else None,
            "layer_count": _safe(lambda: len(list(prj[Project.FixedSerial.LayerContainer]))),
            "worldview_top_level_count": _safe(lambda: int(self.wv(prj).Count)),  # direct members only, not nested
        }
        return info

    def h_list_entities(self, p):
        """List model objects with filters and paging.

        Params: type_contains (case-insensitive substring of the type name), layer (exact layer name), name_contains
        (case-insensitive), graphical_only (default True, see walk), limit (200), offset (0).
        Returns {total_matched, returned, offset, counts_by_type, entities:[summarize(...)]}; counts_by_type and
        total_matched cover every match, not just the returned page.
        """
        prj = self.project()
        tf = (p.get("type_contains") or "").lower()
        lf = p.get("layer")
        nf = (p.get("name_contains") or "").lower()
        limit = int(p.get("limit", 200))
        offset = int(p.get("offset", 0))
        out = []
        counts = {}
        matched = 0
        for o in self.walk(self.wv(prj), bool(p.get("graphical_only", True))):
            d = self.summarize(prj, o)
            if tf and tf not in d["type"].lower():
                continue
            if lf and d.get("layer") != lf:
                continue
            if nf and nf not in (d.get("name") or "").lower():
                continue
            counts[d["type"]] = counts.get(d["type"], 0) + 1
            if matched >= offset and len(out) < limit:
                out.append(d)
            matched += 1
        return {"total_matched": matched, "returned": len(out), "offset": offset, "counts_by_type": counts, "entities": out}

    def h_get_entity(self, p):
        """Everything readable about one object, found by reflection.

        Params: serial (required), property_filter (case-insensitive substring of property names), units.
        Returns summarize(...) plus "properties" {name: jsonable(value, depth 1)} for every readable, non-indexed
        .NET property (a property that throws shows "<error: ...>"), and for objects with elements (ElementCount,
        e.g. linestrings) "vertices": up to 2000 [{x, y, z}] in the requested units.
        Property values are raw: lengths in them are meters, not converted.
        """
        prj = self.project()
        o = self.lookup(prj, p["serial"])
        d = self.summarize(prj, o)
        props = {}
        # Skipped: IsProtected, Members, Coordinates, SyncRoot (the reason for this list isn't recorded; Members and
        # Coordinates are collections, SyncRoot is a lock object).
        skip = set(["IsProtected", "Members", "Coordinates", "SyncRoot"])
        flt = (p.get("property_filter") or "").lower()
        for pi in o.GetType().GetProperties():
            # Indexed properties (indexers) need arguments and can't be read with GetValue(o, None).
            if pi.GetIndexParameters().Length or not pi.CanRead or pi.Name in skip:
                continue
            if flt and flt not in pi.Name.lower():
                continue
            try:
                props[pi.Name] = jsonable(pi.GetValue(o, None), 1)
            except Exception as ex:
                props[pi.Name] = "<error: " + _err_text(ex) + ">"
        d["properties"] = props
        n = _safe(lambda: int(o.ElementCount))
        if n:
            units = p.get("units", "display")
            verts = []
            for i in range(min(n, 2000)):
                pos = _safe(lambda: o.ElementAt(i).Position)
                if pos is not None:
                    verts.append({"x": self.from_m(prj, pos.X, units), "y": self.from_m(prj, pos.Y, units), "z": self.from_m(prj, pos.Z, units)})
            d["vertices"] = verts
        return d

    def h_list_points(self, p):
        """List survey points (TbcPoint.GetAllPoints) with filters and paging.

        Params: name_contains (case-insensitive), layer (exact name), limit (500), offset (0), units.
        Returns {units, total_matched, returned, points:[{serial, name, layer, feature_code, easting, northing,
        elevation}]}; coordinates are omitted when the point has no position, elevation is None for a 2D point.
        """
        prj = self.project()
        if TbcPoint is None:
            raise Exception("Point type unavailable")
        units = p.get("units", "display")
        nf = (p.get("name_contains") or "").lower()
        lf = p.get("layer")
        limit = int(p.get("limit", 500))
        offset = int(p.get("offset", 0))
        out = []
        matched = 0
        for pt in TbcPoint.GetAllPoints(prj):
            name = _safe(lambda: str(pt.Name), "")
            if nf and nf not in name.lower():
                continue
            layer = self.layer_name(prj, _safe(lambda: pt.Layer))
            if lf and layer != lf:
                continue
            # Position and feature code are only read for points on the returned page.
            if matched >= offset and len(out) < limit:
                pos = _safe(lambda: pt.Position)
                d = {"serial": int(pt.SerialNumber), "name": name, "layer": layer,
                     "feature_code": _safe(lambda: str(pt.FeatureCode) if pt.FeatureCode else None)}
                if pos is not None:
                    d["easting"] = self.from_m(prj, pos.X, units)
                    d["northing"] = self.from_m(prj, pos.Y, units)
                    d["elevation"] = self.from_m(prj, pos.Z, units)
                out.append(d)
            matched += 1
        return {"units": units, "total_matched": matched, "returned": len(out), "points": out}

    def h_list_layers(self, p):
        """List the project's layers.

        Params: with_counts (default True; False skips counting each layer's members and returns None).
        Returns {layers:[{serial, name, visible, locked, color ("#RRGGBB"), member_count}]}. Members of the layer
        container without a Name are skipped.
        """
        prj = self.project()
        out = []
        for l in prj[Project.FixedSerial.LayerContainer]:
            if not hasattr(l, "Name"):
                continue
            out.append({"serial": int(l.SerialNumber), "name": str(l.Name),
                        "visible": _safe(lambda: bool(l.Visible)), "locked": _safe(lambda: bool(l.Locked)),
                        "color": jsonable(_safe(lambda: l.DefaultColor)),
                        "member_count": _safe(lambda: len(list(l.Members))) if p.get("with_counts", True) else None})
        return {"layers": out}

    def h_list_surfaces(self, p):
        """List every surface (Model3D) in the model.

        Params: units. Returns {units, surfaces:[{serial, name, layer, vertices, triangles, min_elevation,
        max_elevation}]}; elevations converted from meters.
        """
        prj = self.project()
        if Model3D is None:
            raise Exception("Model3D type unavailable")
        units = p.get("units", "display")
        out = []
        for o in self.walk(self.wv(prj), False):
            if isinstance(o, Model3D):
                out.append({"serial": int(o.SerialNumber), "name": _safe(lambda: str(o.Name)),
                            "layer": self.layer_name(prj, _safe(lambda: o.Layer)),
                            "vertices": _safe(lambda: int(o.NumberOfVertices)),
                            "triangles": _safe(lambda: int(o.NumberOfTrianglesWithMaterial)),
                            "min_elevation": self.from_m(prj, _safe(lambda: o.MinElevation), units),
                            "max_elevation": self.from_m(prj, _safe(lambda: o.MaxElevation), units)})
        return {"units": units, "surfaces": out}

    def h_surface_elevation(self, p):
        """Surface elevation at a list of x/y positions.

        Params: surface (serial or name, see find_surface), points [{x, y}], units (applies to both input x/y and
        output z). Returns {surface, units, results:[{x, y, z, on_surface}]}; x/y are echoed as given, z is None and
        on_surface False where PickSurface fails or returns no elevation.
        PickSurface has an out parameter: IronPython passes it as clr.Reference[Point3D]() and reads .Value.
        """
        prj = self.project()
        units = p.get("units", "display")
        s = self.find_surface(prj, p["surface"])
        out = []
        for q in p["points"]:
            ref = clr.Reference[Point3D]()
            # Point3D(x, y) is a 2D position (Z undefined); PickSurface fills ref with the point on the surface.
            ok = _safe(lambda: s.PickSurface(Point3D(self.to_m(prj, q["x"], units), self.to_m(prj, q["y"], units)), ref), False)
            z = self.from_m(prj, ref.Value.Z, units) if ok else None
            out.append({"x": q["x"], "y": q["y"], "z": z, "on_surface": bool(ok) and z is not None})
        return {"surface": str(s.Name), "units": units, "results": out}

    def h_get_selection(self, p):
        """What is selected in TBC now. Params: limit (500). Returns {count (all selected), entities (first `limit`)}."""
        prj = self.project()
        out = [self.summarize(prj, o) for o in GlobalSelection.SelectedMembers(prj)]
        return {"count": len(out), "entities": out[:int(p.get("limit", 500))]}

    def h_set_selection(self, p):
        """Replace TBC's selection with these serials. Params: serials ([] clears). Returns {selected: count}.

        GlobalSelection.Items(prj).Set takes a .NET List[UInt32]. Not wrapped in a transaction (selection is not a
        model change). The server's delete_entities tool selects this way and then runs TBC's Delete command.
        """
        prj = self.project()
        lst = List[UInt32]()
        for s in p.get("serials", []):
            lst.Add(UInt32(int(s)))
        GlobalSelection.Items(prj).Set(lst, True)
        return {"selected": lst.Count}

    def h_list_commands(self, p):
        """List TBC's command keys and captions (CommandProcessor.CommandList, about 1180 commands).

        Params: contains (case-insensitive substring of key or caption), limit (300). Returns {count (all matches),
        commands (first `limit`, sorted by key):[{key, caption}]}. "_" (the access-key marker) is removed from
        captions. Works without a project.
        """
        if TrimbleOffice is None:
            raise Exception("TrimbleOffice unavailable")
        f = (p.get("contains") or "").lower()
        out = []
        for kv in TrimbleOffice.TheOffice.CommandProcessor.CommandList:
            key = str(kv.Key)
            cap = _safe(lambda: str(kv.Value.Caption).replace("_", ""), "")
            if f and f not in key.lower() and f not in cap.lower():
                continue
            out.append({"key": key, "caption": cap})
        out.sort(key=lambda d: d["key"])
        return {"count": len(out), "commands": out[:int(p.get("limit", 300))]}

    # ----- write -----------------------------------------------------------
    # Every write below runs its changes inside transact(), so each request is a single undo step in TBC.
    def h_create_points(self, p):
        """Create survey points (one undo step "MCP: create points").

        Params: points [{name, easting, northing, elevation (optional; omitted = 2D point), layer (name or serial,
        optional; a missing layer name is created)}], units. Returns {created, points:[{serial, name}]}.
        The server's create_points tool picks the point names (next free number) and sends points with feature
        codes through TBC's Create Point panel instead; this handler uses the names it is given and sets no codes.
        """
        prj = self.project()
        if TbcPoint is None:
            raise Exception("Point type unavailable")
        units = p.get("units", "display")
        pts = p["points"]
        def work():
            """Inside the transaction: create each point, give it a position (meters) and a layer."""
            made = []
            for q in pts:
                pt = TbcPoint.CreatePoint(prj, str(q["name"]))
                x = self.to_m(prj, q["easting"], units)
                y = self.to_m(prj, q["northing"], units)
                z = q.get("elevation")
                # Point3D(x, y) without Z makes a 2D point (no elevation).
                pt.AddPosition(Point3D(x, y, self.to_m(prj, z, units)) if z is not None else Point3D(x, y))
                if q.get("layer") is not None:
                    pt.Layer = self.layer_serial(prj, q["layer"])
                made.append({"serial": int(pt.SerialNumber), "name": str(pt.Name)})
            return made
        made = self.transact(prj, "MCP: create points", work)
        return {"created": len(made), "points": made}

    def h_create_linestring(self, p):
        """Create a linestring of straight segments (one undo step "MCP: create linestring").

        Params: vertices [{x, y, z (optional)}] (at least 2), closed (bool), name, layer (name or serial), units.
        Returns {serial, name, vertices (element count)}.
        Built the SDK way: add an empty Linestring to the WorldView (wv.Add takes a .NET Type, hence
        clr.GetClrType), then append one element per vertex made by ElementFactory as a straight segment with an
        XYZ location.
        """
        prj = self.project()
        if _ls is None:
            raise Exception("Linestring types unavailable")
        Linestring, ElementFactory, IStraightSegment, IXYZLocation = _ls
        units = p.get("units", "display")
        verts = p["vertices"]
        if len(verts) < 2:
            raise Exception("need at least 2 vertices")
        def work():
            """Inside the transaction: create the linestring, its elements, then name/layer/closed."""
            l = self.wv(prj).Add(clr.GetClrType(Linestring))
            for v in verts:
                e = ElementFactory.Create(clr.GetClrType(IStraightSegment), clr.GetClrType(IXYZLocation))
                x = self.to_m(prj, v["x"], units)
                y = self.to_m(prj, v["y"], units)
                z = v.get("z")
                e.Position = Point3D(x, y, self.to_m(prj, z, units)) if z is not None else Point3D(x, y)
                l.AppendElement(e)
            if p.get("closed"):
                # Tries IsClosed, then Closed, and uses the first one that can be set; if neither works the
                # linestring is silently left open.
                for attr in ("IsClosed", "Closed"):
                    try:
                        setattr(l, attr, True)
                        break
                    except:
                        pass
            if p.get("name"):
                l.Name = str(p["name"])
            if p.get("layer") is not None:
                l.Layer = self.layer_serial(prj, p["layer"])
            return {"serial": int(l.SerialNumber), "name": _safe(lambda: str(l.Name)), "vertices": int(l.ElementCount)}
        return self.transact(prj, "MCP: create linestring", work)

    def h_create_layer(self, p):
        """Find or create a layer by name, optionally setting its default color (one undo step "MCP: create layer").

        Params: name, color (HTML color, e.g. "#FF0000", parsed by ColorTranslator.FromHtml). An existing layer of
        that name is reused (and recolored if color is given). Returns {serial, name}.
        """
        prj = self.project()
        def work():
            """Inside the transaction: FindOrCreateLayer, then set DefaultColor if asked."""
            l = Layer.FindOrCreateLayer(prj, str(p["name"]))
            if p.get("color"):
                l.DefaultColor = ColorTranslator.FromHtml(str(p["color"]))
            return {"serial": int(l.SerialNumber), "name": str(l.Name)}
        return self.transact(prj, "MCP: create layer", work)

    def h_set_properties(self, p):
        """Set .NET properties on one or more objects (one undo step "MCP: set properties").

        Params: properties {PropertyName: value}, serials (list) or serial. Values are assigned with setattr as
        given, with two conversions: "Layer" accepts a layer name (found or created) or serial, and any property
        ending in "Color" accepts an HTML color string. Lengths are not converted (TBC properties are in meters).
        If any assignment fails the whole request raises and the transaction rolls back.
        Returns {updated: [serials], properties: [names]}.
        """
        prj = self.project()
        props = p["properties"]
        serials = p.get("serials") or [p["serial"]]
        def work():
            """Inside the transaction: apply every property to every object."""
            done = []
            for s in serials:
                o = self.lookup(prj, s)
                for k, v in props.items():
                    if k == "Layer":
                        v = self.layer_serial(prj, v)
                    elif k.endswith("Color") and isinstance(v, str):
                        v = ColorTranslator.FromHtml(v)
                    setattr(o, k, v)
                done.append(int(s))
            return done
        done = self.transact(prj, "MCP: set properties", work)
        return {"updated": done, "properties": list(props.keys())}

    def h_delete_entities(self, p):
        """Remove objects by serial from their containers in code (one undo step "MCP: delete").

        Params: serials. Returns {deleted: [serials]}.
        Each object is removed from its site (the container returned by GetSite(), if it has Remove), else from the
        WorldView. NOTE: the MCP server's delete_entities TOOL does not use this handler; it selects the objects and
        runs TBC's own Delete command and refuses import records (see working_safely_in_tbc and
        home_import_export: deleting an import's FileProperties record broke the next import). This handler has
        no such guard; tests/cad_edit_tests.py calls it directly to clean up.
        """
        prj = self.project()
        serials = [int(s) for s in p["serials"]]
        def work():
            """Inside the transaction: remove each object from its site or the WorldView."""
            gone = []
            for s in serials:
                o = self.lookup(prj, s)
                site = _safe(lambda: o.GetSite())
                if site is not None and hasattr(site, "Remove"):
                    site.Remove(UInt32(s))
                else:
                    self.wv(prj).Remove(UInt32(s))
                gone.append(s)
            return gone
        return {"deleted": self.transact(prj, "MCP: delete", work)}

    def h_save_project(self, p):
        """Save the current project through TBC's UI-level project object (CurrentProject.Save()). Returns {saved}."""
        if TrimbleOffice is None:
            raise Exception("TrimbleOffice unavailable")
        return {"saved": bool(TrimbleOffice.TheOffice.CurrentProject.Save())}

    @async_ui
    def h_run_command(self, p):
        """Run a TBC command by key, like clicking its ribbon button. Asynchronous (@async_ui).

        Params: key (from list_commands), args (list, passed as a .NET Object[]; usually empty).
        The reply {"queued": true} is sent before the command runs, because of panels or dialogs the command
        may open, which would hold up a synchronous UI-thread call. Errors are swallowed (_safe_call); the server's
        run_command tool checks the license, known-danger confirmation, idle state and pacing before calling this.
        """
        args = p.get("args") or []
        TrimbleOffice.TheOffice.CommandProcessor.ExecuteCommand(str(p["key"]), True, Array[Object](args))

    def h_execute_python(self, p):
        """Run IronPython code inside TBC on the UI thread and return what it printed and assigned to `result`.

        Params: code (source text), transaction (default True).
        Namespace (fresh dict each call, nothing persists between calls): clr, project and prj (current project or
        None), wv (its WorldView or None), bridge (this TbcHandlers, for factor/lookup/walk/transact ...), jsonable,
        result (None), plus whichever of TbcPoint, Point3D, Layer, Project, Model3D, GlobalSelection, TrimbleOffice,
        TransactMethodCall, Client, LinearType were imported. The code is also the module's globals, so functions
        it defines see these names (the ipy helpers rely on that).
        With a project open and transaction True the code runs inside transact() as the undo step "MCP: python";
        an exception rolls it back. Errors propagate and become an ok=false reply with the traceback.
        Returns {stdout: last 20000 characters printed, result: jsonable(result, depth 3)}.
        The MCP server can disable its execute_python tool (TBC_MCP_ALLOW_PYTHON=0), but run_ipy() and other
        server internals use this method too.
        """
        prj = None
        try:
            prj = self.project()
        except:
            pass  # no project open: still allow code that doesn't need one
        ns = {"clr": clr, "project": prj, "prj": prj, "wv": self.wv(prj) if prj is not None else None,
              "bridge": self, "jsonable": jsonable, "result": None}
        # Names whose import never ran (core TBC import failed) are left out; optional types that failed are None.
        for name in ("TbcPoint", "Point3D", "Layer", "Project", "Model3D", "GlobalSelection", "TrimbleOffice",
                     "TransactMethodCall", "Client", "LinearType"):
            if name in globals():
                ns[name] = globals()[name]
        code = p["code"]
        # print() output is captured by swapping sys.stdout; restored in `finally` even if the code raises.
        buf = StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            def run():
                """Compile and run the code in ns ("<mcp>" is the file name shown in tracebacks)."""
                exec(compile(code, "<mcp>", "exec"), ns)
            if prj is not None and p.get("transaction", True):
                self.transact(prj, "MCP: python", run)
            else:
                run()
        finally:
            sys.stdout = old
        return {"stdout": buf.getvalue()[-20000:], "result": jsonable(ns.get("result"), 3)}
