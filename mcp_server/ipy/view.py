# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# IronPython 3.4 code executed INSIDE TBC by the MCP server. Prepended: ACTION, ARGS. Sets `result`.
# What the user is looking at: the active graphic view's visible extents, a screenshot of it, and setting
# the visible area. Coordinates in display units (x = easting, y = northing) unless ARGS["units"] == "meters".
"""View helper run inside TBC through the bridge's execute_python (backs the server's tbc_view tool).

How it is called
----------------
The server's run_ipy("view", ACTION, ARGS) reads this file fresh on every call, prepends `ACTION` and `ARGS`, and
runs it through the bridge's execute_python (transaction=False: changing what the view shows is not a model
change). It runs in the bridge's namespace, so TrimbleOffice, Point3D, prj and bridge are used without imports.
The last line dispatches ACTION and stores the return value in `result`.

Callers: t_view() (actions info / screenshot / set_extents) and view_covered_by_other_app() (screen_rect) in
mcp_server/tbc_mcp_server.py; tests/tbc_testkit.py and tests/cad_edit_tests.py call "info".

Units: TBC's view extents are model coordinates in meters. They are multiplied by bridge.factor(prj) (meters ->
display units) on the way out and divided by it on the way in, unless ARGS["units"] == "meters" (factor 1).

Actions
-------
info        ARGS: units -> {"view": window title, "units": "display"|"meters", "min": {x, y}, "max": {x, y},
            "center": {x, y}, "width", "height" (visible area), "pixels": {w, h} (client size),
            "views_open": [titles of every open graphic view]}
screen_rect ARGS: none -> {"left", "top", "width", "height"} of the active view's client area in screen pixels.
            The server samples points in this rectangle to make sure no other application's window covers it.
screenshot  ARGS: units, max_width (default 1400), path (optional; default %TEMP%\\tbc_mcp_view.png)
            -> info's keys + {"path", "image_size": {w, h}}. Writes a PNG file.
set_extents ARGS: units, and either zoom_extents=True or min {x, y} + max {x, y} -> info's keys after the change.

Privacy: screenshot copies screen pixels, so it would capture whatever window is on top. The server's tbc_view
tool runs view_covered_by_other_app() first and refuses when another application covers the view (README,
"Built-in safety": screenshots capture TBC only).
"""
import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
from System.Windows.Forms import Application, Form
from System.Drawing import Bitmap, Graphics, Point, Size
from System.Drawing.Imaging import ImageFormat
from System.IO import Path


# ---------------------------------------------------------------------------
# Finding the graphic view
# ---------------------------------------------------------------------------
def _views():
    """Every visible open WinForms form that is a graphic view (Plan View and similar).

    Views are recognised by having a GetViewExtents method (duck typing) rather than by class name. Forms that
    throw while being inspected are skipped.
    """
    out = []
    for f in Application.OpenForms:
        try:
            if hasattr(f, "GetViewExtents") and f.Visible:
                out.append(f)
        except Exception:
            pass
    return out


def _active_view():
    """The view the user is working in: TBC's active MDI child if it is a graphic view, else the first one found.

    Raises "No graphic view (Plan View) is open in TBC" when there is none.
    """
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
    """Meters -> output units factor: 1.0 for units="meters", else the project's display factor (bridge.factor).

    Reads the global ARGS (the same dict the actions receive as `args`); prj and bridge come from the bridge's
    execute_python namespace.
    """
    return 1.0 if ARGS.get("units") == "meters" else bridge.factor(prj)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def info(args):
    """ACTION "info": what the active view shows (see the module docstring for the shape)."""
    v = _active_view()
    # GetViewExtents has two out parameters (the min and max corner); IronPython passes them as
    # clr.Reference[Point3D] objects and reads .Value afterwards.
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
    # ClientRectangle is relative to the view; RectangleToScreen turns it into screen pixel coordinates.
    r = v.RectangleToScreen(v.ClientRectangle)
    return {"left": r.Left, "top": r.Top, "width": r.Width, "height": r.Height}


def screenshot(args):
    """Copy the view's on-screen pixels (what the user sees) to a PNG. The server first checks that no other
    application's window covers the view (otherwise we would capture someone else's content).

    args: max_width (default 1400; wider captures are scaled down keeping the aspect ratio), path (PNG file to
    write; default %TEMP%\\tbc_mcp_view.png, overwritten each time). Returns info(args) plus "path" and
    "image_size". Bitmaps are disposed explicitly to release their native GDI+ memory.
    """
    v = _active_view()
    r = v.RectangleToScreen(v.ClientRectangle)
    bmp = Bitmap(r.Width, r.Height)
    g = Graphics.FromImage(bmp)
    try:
        # CopyFromScreen grabs the pixels currently on screen at that rectangle (not a render of the view).
        g.CopyFromScreen(Point(r.Left, r.Top), Point(0, 0), Size(r.Width, r.Height))
    finally:
        g.Dispose()
    maxw = int(args.get("max_width", 1400))
    if bmp.Width > maxw:
        h = int(bmp.Height * maxw / float(bmp.Width))
        small = Bitmap(bmp, Size(maxw, h))  # Bitmap(image, size) makes a resized copy
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
    """ACTION "set_extents": change what the active view shows, then return info(args).

    args: zoom_extents=True (the view's ZoomExtents) or min {x, y} and max {x, y} corners in the requested units,
    converted to meters (divided by the factor) for SetViewExtents. Point3D(x, y) is a 2D point (no elevation).
    """
    v = _active_view()
    f = _f()
    if args.get("zoom_extents"):
        v.ZoomExtents()
    else:
        lo, hi = args["min"], args["max"]
        v.SetViewExtents(Point3D(lo["x"] / f, lo["y"] / f), Point3D(hi["x"] / f, hi["y"] / f))
    return info(args)


# Dispatch: the server prepends ACTION/ARGS; the bridge returns `result`. An unknown ACTION raises KeyError.
result = {"info": info, "screenshot": screenshot, "set_extents": set_extents, "screen_rect": screen_rect}[ACTION](ARGS)
