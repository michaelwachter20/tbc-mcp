# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# IronPython 3.4 code executed INSIDE TBC by the MCP server. Prepended: ACTION, ARGS. Sets `result`.
# What the user is looking at: the active graphic view's visible extents, a screenshot of it, and setting
# the visible area. Coordinates in display units (x = easting, y = northing) unless ARGS["units"] == "meters".
import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
from System.Windows.Forms import Application, Form
from System.Drawing import Bitmap, Graphics, Point, Size
from System.Drawing.Imaging import ImageFormat
from System.IO import Path


def _views():
    out = []
    for f in Application.OpenForms:
        try:
            if hasattr(f, "GetViewExtents") and f.Visible:
                out.append(f)
        except Exception:
            pass
    return out


def _active_view():
    vs = _views()
    if not vs:
        raise Exception("No graphic view (Plan View) is open in TBC")
    mf = TrimbleOffice.TheOffice.MainForm
    try:
        a = mf.ActiveMdiChild
        if a is not None and a in vs:
            return a
    except Exception:
        pass
    return vs[0]


def _f():
    return 1.0 if ARGS.get("units") == "meters" else bridge.factor(prj)


def info(args):
    v = _active_view()
    lo, hi = clr.Reference[Point3D](), clr.Reference[Point3D]()
    v.GetViewExtents(lo, hi)
    f = _f()
    a, b = lo.Value, hi.Value
    out = {"view": str(v.Text), "units": "meters" if ARGS.get("units") == "meters" else "display",
           "min": {"x": a.X * f, "y": a.Y * f}, "max": {"x": b.X * f, "y": b.Y * f},
           "center": {"x": (a.X + b.X) / 2 * f, "y": (a.Y + b.Y) / 2 * f},
           "width": abs(b.X - a.X) * f, "height": abs(b.Y - a.Y) * f,
           "pixels": {"w": v.ClientSize.Width, "h": v.ClientSize.Height},
           "views_open": [str(x.Text) for x in _views()]}
    return out


def screen_rect(args):
    """Screen rectangle of the active view (for the server's 'is it covered by another window?' check)."""
    v = _active_view()
    r = v.RectangleToScreen(v.ClientRectangle)
    return {"left": r.Left, "top": r.Top, "width": r.Width, "height": r.Height}


def screenshot(args):
    """Copy the view's on-screen pixels (what the user sees) to a PNG. The server first checks that no other
    application's window covers the view (otherwise we would capture someone else's content)."""
    v = _active_view()
    r = v.RectangleToScreen(v.ClientRectangle)
    bmp = Bitmap(r.Width, r.Height)
    g = Graphics.FromImage(bmp)
    try:
        g.CopyFromScreen(Point(r.Left, r.Top), Point(0, 0), Size(r.Width, r.Height))
    finally:
        g.Dispose()
    maxw = int(args.get("max_width", 1400))
    if bmp.Width > maxw:
        h = int(bmp.Height * maxw / float(bmp.Width))
        small = Bitmap(bmp, Size(maxw, h))
        bmp.Dispose()
        bmp = small
    path = args.get("path") or Path.Combine(Path.GetTempPath(), "tbc_mcp_view.png")
    bmp.Save(path, ImageFormat.Png)
    w, h = bmp.Width, bmp.Height
    bmp.Dispose()
    out = info(args)
    out.update({"path": path, "image_size": {"w": w, "h": h}})
    return out


def set_extents(args):
    v = _active_view()
    f = _f()
    if args.get("zoom_extents"):
        v.ZoomExtents()
    else:
        lo, hi = args["min"], args["max"]
        v.SetViewExtents(Point3D(lo["x"] / f, lo["y"] / f), Point3D(hi["x"] / f, hi["y"] / f))
    return info(args)


result = {"info": info, "screenshot": screenshot, "set_extents": set_extents, "screen_rect": screen_rect}[ACTION](ARGS)
