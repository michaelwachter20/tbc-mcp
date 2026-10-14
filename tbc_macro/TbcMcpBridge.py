# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
TBC MCP Bridge macro.

Runs inside Trimble Business Center (IronPython 3.4) and exposes the open
project over a localhost TCP socket so an external MCP server can drive it.

Click the macro once to start the bridge, click again to stop it.

Protocol: one JSON object per line.
  request : {"id": 1, "token": "...", "method": "ping", "params": {}}
  response: {"id": 1, "ok": true, "result": ...}
            {"id": 1, "ok": false, "error": "...", "traceback": "..."}

Connection info (port + token) is written to %TEMP%\\tbc_mcp_bridge.json.
NOTE: keep this file IronPython 3.4 compatible (no f-strings, no annotations).
"""
import clr
import sys
import json
import math
import traceback

clr.AddReference("System")
clr.AddReference("WindowsBase")
clr.AddReference("System.Drawing")
from System import Func, Action, Object, Array, Guid, AppDomain, Environment, DateTime, UInt32
from System.Collections.Generic import List
from System.Threading import Thread, ThreadStart
from System.Net import IPAddress
from System.Net.Sockets import TcpListener
from System.IO import StreamReader, StreamWriter, Path, File, FileInfo
from System.Text import UTF8Encoding
from System.Windows.Threading import Dispatcher, DispatcherPriority
from System.Drawing import Bitmap, ColorTranslator

try:
    from io import StringIO
except ImportError:
    from StringIO import StringIO

# ---------------------------------------------------------------------------
# TBC imports (guarded so the socket core can be tested outside TBC)
# ---------------------------------------------------------------------------
IN_TBC = True
_IMPORT_ERRORS = []
for _asm in ("Trimble.Sdk.Interfaces", "Trimble.Sdk.Core", "Trimble.Sdk.Geometry", "Trimble.Sdk.Coordinates",
             "Trimble.Sdk.Surface", "Trimble.Sdk.Alignment"):
    try:
        clr.AddReference(_asm)  # TBC preloads these; explicit refs also let tests import them
    except:
        pass
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
    try:
        return fn()
    except Exception as ex:
        _IMPORT_ERRORS.append(label + ": " + str(ex))
        return None

def _imp_point():
    from Trimble.Vce.Coordinates import Point
    return Point

def _imp_model3d():
    from Trimble.Vce.Gem import Model3D
    return Model3D

def _imp_linestring():
    from Trimble.Vce.Alignment.Linestring import Linestring, ElementFactory, IStraightSegment, IXYZLocation
    return (Linestring, ElementFactory, IStraightSegment, IXYZLocation)

def _imp_office():
    clr.AddReference("Trimble.Vce.UI.UIManager")
    from Trimble.Vce.UI.UIManager import TrimbleOffice
    return TrimbleOffice

if IN_TBC:
    TbcPoint = _opt_import("Point", _imp_point)
    Model3D = _opt_import("Model3D", _imp_model3d)
    _ls = _opt_import("Linestring", _imp_linestring)
    TrimbleOffice = _opt_import("TrimbleOffice", _imp_office)
else:
    TbcPoint = Model3D = _ls = TrimbleOffice = None

BRIDGE_VERSION = "0.2.0"
DEFAULT_PORT = 47821
INSTANCE_KEY = "TbcMcpBridge.Instance"
INFO_FILE = Path.Combine(Path.GetTempPath(), "tbc_mcp_bridge.json")


# ---------------------------------------------------------------------------
# Macro entry points
# ---------------------------------------------------------------------------
def Setup(cmdData, macroFileFolder):
    cmdData.Key = "TbcMcpBridge"
    cmdData.CommandName = "TbcMcpBridge"
    cmdData.Caption = "_MCP Bridge (start/stop)"
    try:
        cmdData.DefaultTabKey = "Macros"
        cmdData.DefaultTabGroupKey = "MCP"
        cmdData.ShortCaption = "MCP Bridge OFF"
        cmdData.Version = 0.1
        cmdData.MacroAuthor = "TBC MCP"
        cmdData.ToolTipTitle = "MCP Bridge"
        cmdData.ToolTipTextFormatted = "Start or stop the local bridge that lets an AI assistant (MCP) work with this project."
    except:
        pass
    try:
        cmdData.EnableNoProject = True
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


def _status_icon(size, running):
    """Green (running) or red (stopped) dot used as the ribbon button image."""
    from System.Drawing import Graphics, Color, SolidBrush, Pen, Rectangle
    from System.Drawing.Drawing2D import SmoothingMode
    bmp = Bitmap(size, size)
    g = Graphics.FromImage(bmp)
    try:
        g.SmoothingMode = SmoothingMode.AntiAlias
        fill = Color.FromArgb(40, 200, 70) if running else Color.FromArgb(225, 45, 45)
        edge = Color.FromArgb(20, 110, 40) if running else Color.FromArgb(130, 20, 20)
        m = max(1, size // 8)
        d = size - 2 * m - 1
        g.FillEllipse(SolidBrush(fill), Rectangle(m, m, d, d))
        g.DrawEllipse(Pen(edge, max(1.0, size / 16.0)), Rectangle(m, m, d, d))
        g.FillEllipse(SolidBrush(Color.FromArgb(150, 255, 255, 255)), Rectangle(m + d // 4, m + d // 6, d // 3, d // 4))
    finally:
        g.Dispose()
    return bmp


LOG_FILE = Path.Combine(Path.GetTempPath(), "tbc_mcp_bridge.log")


def _log(text):
    try:
        if File.Exists(LOG_FILE) and FileInfo(LOG_FILE).Length > 200000:
            File.Delete(LOG_FILE)
        File.AppendAllText(LOG_FILE, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + text + "\r\n")
    except:
        pass


def _install_close_reset():
    """Set the light back to OFF when TBC's main window starts closing, before TBC saves its ribbon layout."""
    if AppDomain.CurrentDomain.GetData("TbcMcpBridge.CloseHook") is not None:
        return
    try:
        def on_closing(sender, e):
            _update_ribbon(False)
            _log("main window closing -> light OFF")
        TrimbleOffice.TheOffice.MainForm.FormClosing += on_closing
        AppDomain.CurrentDomain.SetData("TbcMcpBridge.CloseHook", on_closing)
    except Exception as ex:
        _log("could not hook FormClosing: " + _err_text(ex))


def _bridge_actually_running():
    srv = AppDomain.CurrentDomain.GetData(INSTANCE_KEY)
    if srv is None:
        return False
    try:
        return bool(srv.is_alive())
    except:
        return False


def _start_status_monitor():
    """Every 2 s (on the UI thread) make the light match whether the bridge is really listening."""
    if AppDomain.CurrentDomain.GetData("TbcMcpBridge.Monitor") is not None:
        return
    try:
        clr.AddReference("System.Windows.Forms")
        from System.Windows.Forms import Timer
        state = {"shown": None}
        def tick(sender, e):
            alive = _bridge_actually_running()
            if alive != state["shown"]:
                srv = AppDomain.CurrentDomain.GetData(INSTANCE_KEY)
                if not alive and srv is not None:
                    # bridge died on its own: drop the dead instance so the next click starts fresh
                    AppDomain.CurrentDomain.SetData(INSTANCE_KEY, None)
                    _log("bridge no longer listening -> light OFF")
                if _update_ribbon(alive, getattr(srv, "port", None)):
                    state["shown"] = alive
        t = Timer()
        t.Interval = 2000
        t.Tick += tick
        t.Start()
        AppDomain.CurrentDomain.SetData("TbcMcpBridge.Monitor", t)
    except Exception as ex:
        _log("could not start status monitor: " + _err_text(ex))


def _schedule_startup_reset(tries=[0]):
    try:
        from System.Windows.Threading import DispatcherPriority
        def attempt():
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
    """Recolor the macro's ribbon button (Macros tab > MCP) to show bridge state. Returns True on success."""
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
    def __init__(self, handlers, dispatcher=None, port=DEFAULT_PORT):
        self.handlers = handlers
        self.dispatcher = dispatcher
        self.port = port
        self.token = Guid.NewGuid().ToString("N")
        self.listener = None
        self.running = False

    def start(self):
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
        self.stop()

    def is_alive(self):
        """True only if the server is actually listening (accept thread alive, listener bound)."""
        try:
            return bool(self.running and self.accept_thread.IsAlive and self.listener.Server.IsBound)
        except:
            return False

    def stop(self):
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
        info = {"port": self.port, "token": self.token, "pid": _pid(),
                "version": BRIDGE_VERSION, "started": DateTime.Now.ToString("o")}
        File.WriteAllText(INFO_FILE, json.dumps(info))

    def _accept_loop(self):
        while self.running:
            try:
                client = self.listener.AcceptTcpClient()
            except:
                break
            def make(c):
                return lambda: self._serve_client(c)
            t = Thread(ThreadStart(make(client)))
            t.IsBackground = True
            t.Start()

    def _serve_client(self, client):
        try:
            stream = client.GetStream()
            enc = UTF8Encoding(False)
            reader = StreamReader(stream, enc)
            writer = StreamWriter(stream, enc)
            writer.AutoFlush = True
            while self.running:
                line = reader.ReadLine()
                if line is None:
                    break
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
        rid = None
        try:
            req = json.loads(line)
            rid = req.get("id")
            if req.get("token") != self.token:
                return json.dumps({"id": rid, "ok": False, "error": "invalid token"})
            method = req.get("method", "")
            params = req.get("params") or {}
            fn = getattr(self.handlers, "h_" + method, None)
            if fn is None:
                return json.dumps({"id": rid, "ok": False, "error": "unknown method: " + method})
            if getattr(fn, "async_ui", False) and self.dispatcher is not None:
                # fire-and-forget on the UI thread (e.g. commands that open dialogs)
                self.dispatcher.BeginInvoke(DispatcherPriority.Background, Action(lambda: _safe_call(fn, params)))
                return json.dumps({"id": rid, "ok": True, "result": {"queued": True}})
            box = {}
            def work():
                try:
                    box["result"] = fn(params)
                except Exception as ex:
                    box["error"] = _err_text(ex)
                    box["traceback"] = traceback.format_exc()
                return None
            if self.dispatcher is not None:
                # Background priority: run only when TBC's UI thread has nothing more important to do, instead of
                # the default Send priority, which can cut into TBC's own graphics/redraw work mid-way.
                self.dispatcher.Invoke(DispatcherPriority.Background, Func[Object](work))
            else:
                work()
            if "error" in box:
                return json.dumps({"id": rid, "ok": False, "error": box["error"], "traceback": box.get("traceback")})
            return json.dumps({"id": rid, "ok": True, "result": jsonable(box.get("result"))})
        except Exception as ex:
            return json.dumps({"id": rid, "ok": False, "error": _err_text(ex), "traceback": traceback.format_exc()})


def _safe_call(fn, params):
    try:
        fn(params)
    except:
        pass


def _pid():
    try:
        from System.Diagnostics import Process
        return Process.GetCurrentProcess().Id
    except:
        return None


def _err_text(ex):
    try:
        return type(ex).__name__ + ": " + str(ex)
    except:
        return "error"


def async_ui(fn):
    fn.async_ui = True
    return fn


# ---------------------------------------------------------------------------
# JSON conversion of .NET values
# ---------------------------------------------------------------------------
_INT_TYPES = ("Byte", "SByte", "Int16", "UInt16", "Int32", "UInt32", "Int64", "UInt64")
_FLOAT_TYPES = ("Single", "Double", "Decimal")

def jsonable(v, depth=2):
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
        return str(v)
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
                if i >= 200:
                    out.append("...")
                    break
                out.append(jsonable(x, depth - 1))
            return out
        except:
            pass
    return str(v)


def _type_name(o):
    n = o.GetType().FullName
    return n[len("Trimble.Vce."):] if n.startswith("Trimble.Vce.") else n


def _safe(fn, default=None):
    try:
        return fn()
    except:
        return default


# ---------------------------------------------------------------------------
# Handlers. Each h_<method>(params) runs on the TBC UI thread.
# ---------------------------------------------------------------------------
class TbcHandlers(object):
    def __init__(self, fallback_project=None):
        self.fallback_project = fallback_project

    # ----- helpers ---------------------------------------------------------
    def project(self):
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
        return prj[Project.FixedSerial.WorldView]

    def factor(self, prj):
        """meters -> display units"""
        return float(prj.Units.Linear.Convert(1.0, LinearType.Display))

    def unit_name(self, f):
        for name, val in (("meter", 1.0), ("US survey foot", 3.280833333), ("international foot", 3.280839895),
                          ("millimeter", 1000.0), ("centimeter", 100.0), ("kilometer", 0.001)):
            if abs(f - val) < 1e-6 * max(1.0, val):
                return name
        return "unknown (factor " + str(f) + " per meter)"

    def to_m(self, prj, val, units):
        if val is None:
            return None
        return float(val) if units == "meters" else float(val) / self.factor(prj)

    def from_m(self, prj, val, units):
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
        prj.TransactionManager.AddBeginMark(Client.CommandGranularity.Command, caption)
        try:
            with TransactMethodCall(prj.TransactionCollector) as guard:
                r = fn()
                guard.Commit()
            return r
        finally:
            prj.TransactionManager.AddEndMark(Client.CommandGranularity.Command)

    def lookup(self, prj, serial):
        o = prj.Concordance.Lookup(UInt32(int(serial)))
        if o is None:
            raise Exception("No entity with serial " + str(serial))
        return o

    def layer_name(self, prj, serial):
        try:
            l = prj.Concordance.Lookup(serial)
            return l.Name if l is not None else None
        except:
            return None

    def layer_serial(self, prj, name_or_serial):
        if isinstance(name_or_serial, int):
            return UInt32(name_or_serial)
        return Layer.FindOrCreateLayer(prj, str(name_or_serial)).SerialNumber

    def summarize(self, prj, o):
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
        return {"pong": True, "bridge_version": BRIDGE_VERSION, "in_tbc": IN_TBC, "import_errors": _IMPORT_ERRORS}

    def h_project_info(self, p):
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
            "worldview_top_level_count": _safe(lambda: int(self.wv(prj).Count)),
        }
        return info

    def h_list_entities(self, p):
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
        prj = self.project()
        o = self.lookup(prj, p["serial"])
        d = self.summarize(prj, o)
        props = {}
        skip = set(["IsProtected", "Members", "Coordinates", "SyncRoot"])
        flt = (p.get("property_filter") or "").lower()
        for pi in o.GetType().GetProperties():
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
        prj = self.project()
        units = p.get("units", "display")
        s = self.find_surface(prj, p["surface"])
        out = []
        for q in p["points"]:
            ref = clr.Reference[Point3D]()
            ok = _safe(lambda: s.PickSurface(Point3D(self.to_m(prj, q["x"], units), self.to_m(prj, q["y"], units)), ref), False)
            z = self.from_m(prj, ref.Value.Z, units) if ok else None
            out.append({"x": q["x"], "y": q["y"], "z": z, "on_surface": bool(ok) and z is not None})
        return {"surface": str(s.Name), "units": units, "results": out}

    def h_get_selection(self, p):
        prj = self.project()
        out = [self.summarize(prj, o) for o in GlobalSelection.SelectedMembers(prj)]
        return {"count": len(out), "entities": out[:int(p.get("limit", 500))]}

    def h_set_selection(self, p):
        prj = self.project()
        lst = List[UInt32]()
        for s in p.get("serials", []):
            lst.Add(UInt32(int(s)))
        GlobalSelection.Items(prj).Set(lst, True)
        return {"selected": lst.Count}

    def h_list_commands(self, p):
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
    def h_create_points(self, p):
        prj = self.project()
        if TbcPoint is None:
            raise Exception("Point type unavailable")
        units = p.get("units", "display")
        pts = p["points"]
        def work():
            made = []
            for q in pts:
                pt = TbcPoint.CreatePoint(prj, str(q["name"]))
                x = self.to_m(prj, q["easting"], units)
                y = self.to_m(prj, q["northing"], units)
                z = q.get("elevation")
                pt.AddPosition(Point3D(x, y, self.to_m(prj, z, units)) if z is not None else Point3D(x, y))
                if q.get("layer") is not None:
                    pt.Layer = self.layer_serial(prj, q["layer"])
                made.append({"serial": int(pt.SerialNumber), "name": str(pt.Name)})
            return made
        made = self.transact(prj, "MCP: create points", work)
        return {"created": len(made), "points": made}

    def h_create_linestring(self, p):
        prj = self.project()
        if _ls is None:
            raise Exception("Linestring types unavailable")
        Linestring, ElementFactory, IStraightSegment, IXYZLocation = _ls
        units = p.get("units", "display")
        verts = p["vertices"]
        if len(verts) < 2:
            raise Exception("need at least 2 vertices")
        def work():
            l = self.wv(prj).Add(clr.GetClrType(Linestring))
            for v in verts:
                e = ElementFactory.Create(clr.GetClrType(IStraightSegment), clr.GetClrType(IXYZLocation))
                x = self.to_m(prj, v["x"], units)
                y = self.to_m(prj, v["y"], units)
                z = v.get("z")
                e.Position = Point3D(x, y, self.to_m(prj, z, units)) if z is not None else Point3D(x, y)
                l.AppendElement(e)
            if p.get("closed"):
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
        prj = self.project()
        def work():
            l = Layer.FindOrCreateLayer(prj, str(p["name"]))
            if p.get("color"):
                l.DefaultColor = ColorTranslator.FromHtml(str(p["color"]))
            return {"serial": int(l.SerialNumber), "name": str(l.Name)}
        return self.transact(prj, "MCP: create layer", work)

    def h_set_properties(self, p):
        prj = self.project()
        props = p["properties"]
        serials = p.get("serials") or [p["serial"]]
        def work():
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
        prj = self.project()
        serials = [int(s) for s in p["serials"]]
        def work():
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
        if TrimbleOffice is None:
            raise Exception("TrimbleOffice unavailable")
        return {"saved": bool(TrimbleOffice.TheOffice.CurrentProject.Save())}

    @async_ui
    def h_run_command(self, p):
        args = p.get("args") or []
        TrimbleOffice.TheOffice.CommandProcessor.ExecuteCommand(str(p["key"]), True, Array[Object](args))

    def h_execute_python(self, p):
        prj = None
        try:
            prj = self.project()
        except:
            pass
        ns = {"clr": clr, "project": prj, "prj": prj, "wv": self.wv(prj) if prj is not None else None,
              "bridge": self, "jsonable": jsonable, "result": None}
        for name in ("TbcPoint", "Point3D", "Layer", "Project", "Model3D", "GlobalSelection", "TrimbleOffice",
                     "TransactMethodCall", "Client", "LinearType"):
            if name in globals():
                ns[name] = globals()[name]
        code = p["code"]
        buf = StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            def run():
                exec(compile(code, "<mcp>", "exec"), ns)
            if prj is not None and p.get("transaction", True):
                self.transact(prj, "MCP: python", run)
            else:
                run()
        finally:
            sys.stdout = old
        return {"stdout": buf.getvalue()[-20000:], "result": jsonable(ns.get("result"), 3)}
