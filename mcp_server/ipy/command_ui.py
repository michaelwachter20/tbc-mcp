# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# IronPython 3.4 code executed INSIDE TBC by the MCP server (via the bridge's execute_python).
# The server prepends:  ACTION = "<name>"; ARGS = {...}
# and reads `result`. Keep IronPython 3.4 compatible (no f-strings).
#
# Drives TBC command panels (WinForms, plus basic WPF for macro panels): inspect fields with
# their on-screen labels, fill them like a user would (type + tab out so TBC validates),
# press buttons, and list/handle modal dialogs.
import clr
clr.AddReference("System.Windows.Forms")
from System import Action, Decimal, UInt32
from System.Windows.Forms import (Control, TextBoxBase, ComboBox, CheckBox, RadioButton, ButtonBase, Label,
                                  NumericUpDown, Application, Form, ListBox)

try:
    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsFormsIntegration")
    from System.Windows import LogicalTreeHelper, DependencyObject, FrameworkElement
    import System.Windows.Controls as WC
    from System.Windows.Automation.Peers import ButtonAutomationPeer, PatternInterface
    HAVE_WPF = True
except Exception:
    HAVE_WPF = False

MAX_OPTIONS = 60


def _clean(t):
    if t is None:
        return None
    t = str(t).replace("&", "").strip()
    if t.endswith(":"):
        t = t[:-1].strip()
    return t or None


def _cmd():
    ch = TrimbleOffice.TheOffice.MainForm.CommandHost
    return ch, ch.TopCommand


def _wpf_windows():
    """Visible WPF windows on this thread (TBC shows some popups, e.g. 'Feature Library Missing', as WPF)."""
    out = []
    if not HAVE_WPF:
        return out
    try:
        from System.Windows import PresentationSource, Window
        for src in PresentationSource.CurrentSources:
            try:
                w = src.RootVisual
                if isinstance(w, Window) and w.IsVisible:
                    out.append(w)
            except Exception:
                pass
    except Exception:
        pass
    return out


def _modal_forms():
    """Popups/dialogs: modal WinForms forms plus visible WPF windows."""
    out = []
    for f in Application.OpenForms:
        try:
            if f.Visible and f.Modal:
                out.append(f)
        except Exception:
            pass
    return out + _wpf_windows()


def _title(f):
    try:
        return str(f.Title) if HAVE_WPF and isinstance(f, DependencyObject) else str(f.Text)
    except Exception:
        return ""


def _dock_panes():
    """TBC's docked/floating panes (Layer Manager, Properties, Project Explorer, ...): [(title, pane)]."""
    from System.Reflection import BindingFlags
    mf = TrimbleOffice.TheOffice.MainForm
    out = []
    for fi in mf.GetType().GetFields(BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public):
        if fi.FieldType.Name != "UltraDockManager":
            continue
        dm = fi.GetValue(mf)
        if dm is None:
            continue
        for p in dm.ControlPanes:
            try:
                out.append((str(p.Text).strip(), p))
            except Exception:
                pass
    return out


def _find_grids(root):
    from System.Windows.Forms import DataGridView
    out = []

    def walk(c):
        if isinstance(c, DataGridView) or "UltraGrid" in c.GetType().Name:
            out.append(c)
            return
        for k in c.Controls:
            walk(k)
    if not (HAVE_WPF and isinstance(root, DependencyObject)):
        walk(root)
    return out


# ---- Infragistics UltraGrid support (TBC's merge/explode/source lists, spreadsheets) ----
def _is_ultra(g):
    return "UltraGrid" in g.GetType().Name


def _u_rows(g):
    """All rows including expanded child bands: [(row, band_key)]."""
    out = []

    def add(rows):
        for r in rows:
            out.append(r)
            try:
                if r.ChildBands is not None:
                    for cb in r.ChildBands:
                        add(cb.Rows)
            except Exception:
                pass
    add(g.Rows)
    return out


def _u_cols(g):
    res = []
    for b in g.DisplayLayout.Bands:
        for c in b.Columns:
            if not c.Hidden:
                res.append({"band": str(b.Key), "name": str(c.Key), "header": _clean(c.Header.Caption), "type": str(c.DataType.Name)})
    return res


def _u_cell_val(cell):
    return _cell_text(cell.Value)


def _u_row_dict(r):
    d = {"_band": str(r.Band.Key)}
    for c in r.Cells:
        if not c.Column.Hidden:
            d[str(c.Column.Key)] = _u_cell_val(c)
    return d


def _u_match(g, match):
    rows = _u_rows(g)
    if isinstance(match, int):
        return rows[match]
    hits = []
    for r in rows:
        ok = True
        for k, v in match.items():
            if k == "_band":
                if str(r.Band.Key).lower() != str(v).lower():
                    ok = False
                continue
            try:
                cv = _u_cell_val(r.Cells[str(k)])
            except Exception:
                ok = False
                break
            if str(cv).strip().lower() != str(v).strip().lower():
                ok = False
                break
        if ok:
            hits.append(r)
    if len(hits) != 1:
        raise Exception("Row match %s found %d rows (need exactly 1)" % (match, len(hits)))
    return hits[0]


def _u_set(g, r, col, v):
    """Edit an UltraGrid cell through the grid's own edit path (activate -> EnterEditMode -> change -> ExitEditMode).
    Setting cell.Value directly, a mouse click or Space did NOT reach TBC's Merge Points logic; this does."""
    from System import Enum
    UGA = g.GetType().BaseType.Assembly.GetType("Infragistics.Win.UltraWinGrid.UltraGridAction")
    act = lambda name: g.PerformAction(Enum.Parse(UGA, name))
    try:
        p = r.ParentRow
        while p is not None:
            p.Expanded = True
            p = p.ParentRow
    except Exception:
        pass
    cell = r.Cells[col]
    g.Focus()
    g.ActiveRow = r
    g.ActiveCell = cell
    act("EnterEditMode")
    if str(cell.Column.DataType.Name) == "Boolean":
        want = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")
        cur = str(cell.Value).lower() == "true"
        if cur != want:
            act("ToggleCheckbox")
    else:
        cell.Value = v
    act("ExitEditMode")
    try:
        g.UpdateData()
    except Exception:
        pass
    return _u_cell_val(cell)


def _cell_text(v):
    if v is None:
        return None
    tn = v.GetType().Name
    if tn == "Color":
        return "#%02X%02X%02X" % (v.R, v.G, v.B)
    if tn in ("Bitmap", "Image", "Icon"):
        return "[image]"
    if isinstance(v, bool):
        return v
    return str(v)


def _grid_cols(g):
    return [{"name": str(c.Name), "header": _clean(c.HeaderText), "type": c.GetType().Name.replace("DataGridView", ""),
             "read_only": bool(c.ReadOnly)} for c in g.Columns if c.Visible]


def _grids(root):
    out = []
    for g in _find_grids(root):
        if _is_ultra(g):
            out.append({"grid": str(g.Name), "kind": "UltraGrid", "rows": len(_u_rows(g)), "columns": _u_cols(g)})
        else:
            out.append({"grid": str(g.Name), "rows": g.RowCount, "columns": _grid_cols(g)})
    return out


def _grid(root, name):
    gs = _find_grids(root)
    if not gs:
        raise Exception("No grid in this panel")
    if not name:
        return gs[0]
    for g in gs:
        if str(g.Name).lower() == str(name).lower():
            return g
    raise Exception("No grid '%s'. Grids: %s" % (name, [str(g.Name) for g in gs]))


def _col(g, key):
    k = str(key).strip().lower()
    for c in g.Columns:
        if str(c.Name).lower() == k or (_clean(c.HeaderText) or "").lower() == k:
            return c
    raise Exception("No column '%s'. Columns: %s" % (key, [(str(c.Name), _clean(c.HeaderText)) for c in g.Columns]))


def _row(g, match):
    """match = {column: value} (all must match, case-insensitive) or an int row index."""
    if isinstance(match, int):
        return g.Rows[match]
    hits = []
    for r in g.Rows:
        ok = True
        for k, v in match.items():
            cv = _cell_text(r.Cells[_col(g, k).Index].Value)
            if str(cv).strip().lower() != str(v).strip().lower():
                ok = False
                break
        if ok:
            hits.append(r)
    if len(hits) != 1:
        raise Exception("Row match %s found %d rows (need exactly 1)" % (match, len(hits)))
    return hits[0]


def grid_read(args):
    root, _ = _root(args.get("scope"))
    g = _grid(root, args.get("grid"))
    if _is_ultra(g):
        flt = args.get("where") or {}
        rows = []
        for i, r in enumerate(_u_rows(g)):
            d = _u_row_dict(r)
            if flt and not all(str(d.get(k)).lower() == str(v).lower() for k, v in flt.items()):
                continue
            d["_row"] = i
            rows.append(d)
        return {"grid": str(g.Name), "kind": "UltraGrid", "columns": _u_cols(g), "row_count": len(_u_rows(g)),
                "rows": rows[:int(args.get("limit", 200))]}
    cols = [c for c in g.Columns if c.Visible]
    flt = args.get("where") or {}
    rows = []
    for r in g.Rows:
        d = dict((str(c.Name), _cell_text(r.Cells[c.Index].Value)) for c in cols)
        if flt and not all(str(d.get(_col(g, k).Name)).lower() == str(v).lower() for k, v in flt.items()):
            continue
        d["_row"] = r.Index
        rows.append(d)
    lim = int(args.get("limit", 200))
    return {"grid": str(g.Name), "columns": _grid_cols(g), "row_count": g.RowCount, "rows": rows[:lim]}


def grid_set(args):
    """Edit a cell through the grid's normal editing path (CurrentCell -> BeginEdit -> value -> EndEdit)."""
    root, _ = _root(args.get("scope"))
    g = _grid(root, args.get("grid"))
    if _is_ultra(g):
        r = _u_match(g, args["row"])
        now = _u_set(g, r, str(args["column"]), args["value"])
        return {"row": _u_row_dict(r), "column": str(args["column"]), "now": now}
    r = _row(g, args["row"])
    c = _col(g, args["column"])
    if c.ReadOnly:
        raise Exception("Column '%s' is read-only" % c.Name)
    cell = r.Cells[c.Index]
    v = args["value"]
    if isinstance(cell.Value, bool) and not isinstance(v, bool):
        v = str(v).strip().lower() in ("1", "true", "yes", "on")
    g.CurrentCell = cell
    g.BeginEdit(True)
    ec = g.EditingControl
    if ec is not None and hasattr(ec, "Items") and not isinstance(v, bool):
        items = [str(x) for x in ec.Items]
        hit = [i for i, s in enumerate(items) if s.lower() == str(v).lower()]
        if not hit:
            g.CancelEdit()
            g.EndEdit()
            raise Exception("'%s' is not an option for %s. Options: %s" % (v, c.Name, items[:MAX_OPTIONS]))
        ec.SelectedIndex = hit[0]
    elif ec is not None and not isinstance(v, bool):
        ec.Text = str(v)
    else:
        cell.Value = v
    g.EndEdit()
    try:
        g.CommitEdit(0)
    except Exception:
        pass
    return {"row": r.Index, "column": str(c.Name), "now": _cell_text(r.Cells[c.Index].Value)}


def _mouse_click(ctrl, x, y):
    """Feed genuine mouse messages (move, down, up) into a control's own window procedure, in-process.
    The control handles them exactly like a real click; Windows' cross-process input filtering can't drop them."""
    from System import IntPtr, Array, Object
    from System.Windows.Forms import Message
    from System.Reflection import BindingFlags
    wndproc = clr.GetClrType(Control).GetMethod("WndProc", BindingFlags.Instance | BindingFlags.NonPublic)
    lp = IntPtr(((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF))
    for msg, wp in ((0x0200, 0), (0x0201, 1), (0x0202, 0)):  # WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP
        m = Message.Create(ctrl.Handle, msg, IntPtr(wp), lp)
        wndproc.Invoke(ctrl, Array[Object]([m]))


def _fit_column(g, c):
    """Make column c visible WITHOUT horizontal scrolling (a scrolled grid swallowed Layer Manager's red-X click):
    temporarily hide other non-frozen columns (display only), returning the list to restore afterwards."""
    hidden = []
    g.HorizontalScrollingOffset = 0
    if c.Displayed and g.GetCellDisplayRectangle(c.Index, 0 if g.RowCount else -1, False).Width >= c.Width - 1:
        return hidden
    for k in reversed(list(g.Columns)):
        if k.Index == c.Index or k.Frozen or not k.Visible or k.Name in ("LayerName",):
            continue
        k.Visible = False
        hidden.append(k)
        g.PerformLayout()
        if c.Displayed and g.GetCellDisplayRectangle(c.Index, 0, False).Width >= c.Width - 1:
            break
    return hidden


def _type_keys(ctrl, text):
    """Type text into a WinForms control as real keystrokes (WM_KEYDOWN/WM_CHAR/WM_KEYUP via its WndProc), with
    Enter at each line end - for line-by-line command boxes such as Create COGO's 'Line commands' that only parse
    what the user types."""
    from System import IntPtr, Array, Object
    from System.Windows.Forms import Message
    from System.Reflection import BindingFlags
    wndproc = clr.GetClrType(Control).GetMethod("WndProc", BindingFlags.Instance | BindingFlags.NonPublic)

    def send(msg, wp):
        wndproc.Invoke(ctrl, Array[Object]([Message.Create(ctrl.Handle, msg, IntPtr(wp), IntPtr(0))]))
    ctrl.Focus()
    try:
        if ctrl.SelectionLength == 0:  # append, unless the caller selected text to replace
            ctrl.SelectionStart = len(ctrl.Text or "")
    except Exception:
        pass
    for ch in text.replace("\r\n", "\n"):
        if ch == "\b":  # Backspace
            send(0x0100, 0x08)
            send(0x0102, 0x08)
            send(0x0101, 0x08)
            continue
        if ch == "\n":
            send(0x0100, 0x0D)  # WM_KEYDOWN VK_RETURN
            send(0x0102, 0x0D)  # WM_CHAR '\r'
            send(0x0101, 0x0D)  # WM_KEYUP
        else:
            send(0x0102, ord(ch))


def grid_click(args):
    root, _ = _root(args.get("scope"))
    g = _grid(root, args.get("grid"))
    c = _col(g, args["column"])
    hidden = _fit_column(g, c)
    pt = grid_cell_point(args)
    r = g.Rows[pt["row"]]
    # re-verify the row identity right before clicking
    for k, v in (args["row"].items() if isinstance(args["row"], dict) else []):
        if str(_cell_text(r.Cells[_col(g, k).Index].Value)).lower() != str(v).lower():
            raise Exception("Row moved before click; aborted")
    def go():
        try:
            _mouse_click(g, pt["x"], pt["y"])
        except Exception:
            pass
        finally:
            for k in hidden:  # restore the columns hidden to make the cell fit
                try:
                    k.Visible = True
                except Exception:
                    pass
    TrimbleOffice.TheOffice.MainForm.BeginInvoke(Action(go))  # async so a confirmation popup can't block us
    pt["temporarily_hidden_columns"] = [str(k.Name) for k in hidden]
    return pt


def grid_cell_point(args):
    """Scroll a cell into view and return the window handle + client point at its centre, so the server can
    deliver a genuine mouse click (exactly like the user clicking it)."""
    root, _ = _root(args.get("scope"))
    g = _grid(root, args.get("grid"))
    r = _row(g, args["row"])
    c = _col(g, args["column"])
    try:
        if not r.Displayed:
            g.FirstDisplayedScrollingRowIndex = r.Index
    except Exception:
        pass
    try:
        if not c.Displayed and not c.Frozen:
            g.FirstDisplayedScrollingColumnIndex = c.Index  # e.g. Layer Manager's Delete column in a narrow pane
    except Exception:
        pass
    rect = g.GetCellDisplayRectangle(c.Index, r.Index, False)
    if rect.Width <= 0 or rect.Height <= 0:
        raise Exception("Cell is not visible on screen (pane too small or column scrolled away)")
    ident = dict((str(k.Name), _cell_text(r.Cells[k.Index].Value)) for k in g.Columns if k.Visible and not k.GetType().Name.endswith("ImageColumn"))
    return {"hwnd": int(g.Handle.ToInt64()), "x": rect.Left + rect.Width // 2, "y": rect.Top + rect.Height // 2,
            "row": r.Index, "row_values": ident, "column": str(c.Name)}


def _root(scope):
    scope = scope or "command"
    if scope.startswith("pane:"):
        want = scope[5:].strip().lower()
        for title, p in _dock_panes():
            if title.lower() == want:
                if p.Closed:
                    raise Exception("Pane '%s' is closed; open it first (e.g. run_command layermanager)" % title)
                return p.Control, None
        raise Exception("No pane '%s'. Panes: %s" % (scope[5:], [t for t, _ in _dock_panes()]))
    if scope.startswith("dialog"):
        forms = _modal_forms()
        i = int(scope.split(":")[1]) if ":" in scope else 0
        if i >= len(forms):
            raise Exception("No modal dialog #%d is open (open: %d)" % (i, len(forms)))
        return forms[i], None
    ch, cmd = _cmd()
    if cmd is None:
        raise Exception("No TBC command panel is open. Use command_ui_open first.")
    ui = cmd.CommandUI
    if ui is None:
        raise Exception("Command '%s' has no panel UI" % cmd.Key)
    return ui, cmd


# ---------------------------------------------------------------------------
# WinForms field discovery
# ---------------------------------------------------------------------------
def _has_labels(c):
    for k in c.Controls:
        if isinstance(k, Label):
            return True
    return False


def _wrapper(c):
    """Climb from an inner editor to the composite TBC control the user sees as one field."""
    w = c
    for _ in range(3):
        p = w.Parent
        if p is None or isinstance(p, Form) or _has_labels(p):
            break
        if not p.GetType().FullName.startswith("Trimble.Vce.UI.Controls"):
            break
        w = p
    return w


def _label_for(w):
    """Nearest label left of (or above) the field; looks one container further out if needed."""
    r = _label_in(w.Parent, w.Bounds)
    if r is None and w.Parent is not None and w.Parent.Parent is not None and not isinstance(w.Parent, Form):
        pb = w.Parent.Bounds
        b = w.Bounds
        from System.Drawing import Rectangle
        r = _label_in(w.Parent.Parent, Rectangle(b.Left + pb.Left, b.Top + pb.Top, b.Width, b.Height))
    return r


def _label_in(p, wb):
    if p is None:
        return None
    wc = wb.Top + wb.Height / 2.0
    best, bd = None, 1e9
    above, ad = None, 1e9
    for k in p.Controls:
        if not isinstance(k, Label) or not k.Visible or not (k.Text or "").strip() or (k.Text or "").strip() == "?":
            continue
        kb = k.Bounds
        dy = abs((kb.Top + kb.Height / 2.0) - wc)
        if kb.Right <= wb.Left + 6 and dy < max(wb.Height, 16):
            d = (wb.Left - kb.Right) + dy * 3
            if d < bd:
                best, bd = k, d
        elif kb.Bottom <= wb.Top + 6 and abs(kb.Left - wb.Left) < 60:
            d = (wb.Top - kb.Bottom) + abs(kb.Left - wb.Left)
            if d < ad:
                above, ad = k, d
    if best is not None:
        return _clean(best.Text)
    if above is not None:
        return _clean(above.Text)
    return None


def _visible(c):
    try:
        return bool(c.Visible)
    except Exception:
        return True


class Field(object):
    def __init__(self, kind, wrapper, target, label, tech="winforms"):
        self.kind, self.wrapper, self.target, self.label, self.tech = kind, wrapper, target, label, tech
        self.id = None


def _collect(root, include_hidden=False):
    fields, buttons, texts = [], [], []

    def add(kind, c, target, label=None):
        w = _wrapper(c) if label is None else c
        fields.append(Field(kind, w, target, label if label is not None else _label_for(w)))

    def walk(c):
        if not include_hidden and not _visible(c):
            return
        tn = c.GetType().Name
        kids = list(c.Controls)
        client = [k for k in kids if k.Name == "ClientBox"]
        if client:
            add("entity" if hasattr(c, "SetEntity") else "text", c, client[0])
            return
        if tn == "BrowseFile":  # TBC file chooser: a path box (+ Browse button); type the path into it
            box = [k for k in kids if k.Name == "FilePathTextBox" and k.Visible] or [k for k in kids if k.Name == "FilePathComboBox"]
            if box:
                add("text", c, box[0])
                return
        if isinstance(c, CheckBox):
            add("bool", c, c, _clean(c.Text) or _label_for(c))
            return
        if isinstance(c, RadioButton):
            add("radio", c, c, _clean(c.Text) or _label_for(c))
            return
        if isinstance(c, TextBoxBase):
            add("text", c, c)
            return
        if isinstance(c, ComboBox):
            add("choice", c, c)
            return
        if isinstance(c, NumericUpDown):
            add("number", c, c)
            return
        if isinstance(c, ListBox):
            add("list", c, c)
            return
        if tn.startswith("Ultra") and ("Editor" in tn or tn == "UltraCheckEditor"):
            add("ultra", c, c)
            return
        if isinstance(c, ButtonBase) or tn in ("UltraButton", "UltraDropDownButton"):
            if (c.Text or "").strip() or (c.Name and c.Name.lower().endswith("button")):
                buttons.append(c)  # icon-only buttons (e.g. Adjust Traverse's addButton) are pressed by id
            return
        if isinstance(c, Label):
            t = (c.Text or "").strip()
            if t and t != "?" and len(texts) < 150:
                texts.append(c)
            return
        if tn == "ElementHost" and HAVE_WPF:
            try:
                if c.Child is not None:
                    _walk_wpf(c.Child, fields, buttons, texts, include_hidden, [None])
            except Exception:
                pass
            return
        for k in kids:
            walk(k)

    if HAVE_WPF and isinstance(root, DependencyObject):
        _walk_wpf(root, fields, buttons, texts, include_hidden, [None])  # WPF window (popup)
    else:
        walk(root)
    # assign stable ids: control name, de-duplicated
    seen = {}
    for f in fields:
        base = _name_of(f.wrapper) or _name_of(f.target) or (f.label or f.kind).replace(" ", "_")
        n = seen.get(base, 0) + 1
        seen[base] = n
        f.id = base if n == 1 else "%s#%d" % (base, n)
    return fields, buttons, texts


def _name_of(c):
    try:
        n = c.Name
        return str(n) if n else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# WPF (macro panels)
# ---------------------------------------------------------------------------
def _wpf_text(content, depth=0):
    """Text of a WPF Content value (string, TextBlock, AccessText, or a container holding one)."""
    if content is None or depth > 4:
        return None
    if isinstance(content, str):
        return _clean(content)
    try:
        if isinstance(content, WC.TextBlock):
            return _clean(content.Text)
        if isinstance(content, WC.AccessText):
            return _clean(content.Text)
        if isinstance(content, WC.ContentControl):
            return _wpf_text(content.Content, depth + 1)
        if isinstance(content, WC.Panel):
            for ch in content.Children:
                t = _wpf_text(ch, depth + 1)
                if t:
                    return t
    except Exception:
        pass
    return None


def _walk_wpf(o, fields, buttons, texts, include_hidden, last_label):
    if not isinstance(o, DependencyObject):
        return
    try:
        if not include_hidden and isinstance(o, FrameworkElement) and not o.IsVisible:
            return
    except Exception:
        pass
    if isinstance(o, (WC.TextBlock, WC.Label)):
        t = _clean(o.Text) if isinstance(o, WC.TextBlock) else _wpf_text(o.Content)
        if t:
            last_label[0] = t
            texts.append(o)
        return
    if isinstance(o, WC.CheckBox):
        fields.append(Field("bool", o, o, _wpf_text(o.Content) or last_label[0], "wpf"))
        return
    if isinstance(o, WC.RadioButton):
        fields.append(Field("radio", o, o, _wpf_text(o.Content) or last_label[0], "wpf"))
        return
    if isinstance(o, WC.Primitives.ButtonBase):
        if _wpf_text(o.Content):
            buttons.append(o)
        return
    if isinstance(o, WC.TextBox):
        fields.append(Field("text", o, o, last_label[0], "wpf"))
        last_label[0] = None
        return
    if isinstance(o, WC.ComboBox):
        fields.append(Field("choice", o, o, last_label[0], "wpf"))
        last_label[0] = None
        return
    for k in LogicalTreeHelper.GetChildren(o):
        _walk_wpf(k, fields, buttons, texts, include_hidden, last_label)


# ---------------------------------------------------------------------------
# read / write values
# ---------------------------------------------------------------------------
def _item_text(t, x):
    """The text the user sees for a list item: WinForms GetItemText honours DisplayMember / Format, so items that
    are .NET objects (Scale Bar type, Sheet set type, Leader type ...) show their caption, not a type name."""
    try:
        if hasattr(t, "GetItemText"):
            s = str(t.GetItemText(x))
            if s and not s.startswith("<"):
                return s
    except Exception:
        pass
    for attr in ("DisplayText", "DisplayName", "Name", "Caption"):
        try:
            v = getattr(x, attr, None)
            if v is not None and not callable(v):
                return str(v)
        except Exception:
            pass
    return str(x)


def _options(f):
    t = f.target
    try:
        if f.kind in ("choice", "list"):
            return [_item_text(t, x) for i, x in enumerate(t.Items) if i < MAX_OPTIONS]
        if f.kind == "ultra" and hasattr(t, "Items"):
            return [str(x.DisplayText) for i, x in enumerate(t.Items) if i < MAX_OPTIONS]
    except Exception:
        pass
    return None


def _value(f):
    t = f.target
    try:
        if f.kind in ("bool", "radio"):
            return bool(t.IsChecked) if f.tech == "wpf" else bool(t.Checked)
        if f.kind == "number":
            return float(t.Value)
        if f.kind == "entity":
            s = int(f.wrapper.SerialNumber)
            return {"serial": s, "text": str(f.wrapper.Text or "").strip()} if s else ""
        if f.kind == "list":
            if hasattr(t, "CheckedItems"):  # checkbox list: the ticked items are its value
                return [_item_text(t, x) for x in t.CheckedItems]
            return [str(x) for x in t.SelectedItems]
        if f.kind == "ultra" and hasattr(t, "Checked") and not hasattr(t, "Items"):
            return bool(t.Checked)
        if f.kind == "choice" and f.tech == "wpf":
            return str(t.SelectedItem) if t.SelectedItem is not None else (t.Text or "")
        return str(t.Text) if t.Text is not None else ""
    except Exception as ex:
        return "<unreadable: %s>" % ex


def _enabled(f):
    try:
        return bool(f.wrapper.IsEnabled) if f.tech == "wpf" else bool(f.wrapper.Enabled)
    except Exception:
        return True


def _status(f):
    for c in (f.wrapper, f.target):
        try:
            s = c.StatusMessage
            if s:
                return str(s)
        except Exception:
            pass
    return None


def _describe(f):
    d = {"id": f.id, "label": f.label, "kind": f.kind, "value": _value(f)}
    if not _enabled(f):
        d["enabled"] = False
    if f.tech == "winforms" and not _visible(f.wrapper):
        d["visible"] = False
    o = _options(f)
    if o:
        d["options"] = o
    s = _status(f)
    if s:
        d["status"] = s
    tn = f.wrapper.GetType().Name
    if tn not in ("TextBox", "ComboBox", "CheckBox", "RadioButton"):
        d["control"] = tn
    return d


def _btn_text(b):
    if HAVE_WPF and isinstance(b, DependencyObject):
        return _wpf_text(b.Content)
    try:
        return _clean(b.Text)
    except Exception:
        return None


def _btn_desc(b):
    d = {"id": _name_of(b) or _btn_text(b), "text": _btn_text(b)}
    try:
        en = b.IsEnabled if HAVE_WPF and isinstance(b, DependencyObject) else b.Enabled
        if not en:
            d["enabled"] = False
    except Exception:
        pass
    return d


def _live(f):
    try:
        return bool(f.wrapper.IsVisible) if f.tech == "wpf" else bool(f.wrapper.Visible)
    except Exception:
        return True


def _match(fields, key):
    k = str(key).strip().lower()
    # Same-named boxes in alternative groups (e.g. Double Proportioning's North/East/South/West groups all have
    # 'coordinateEdit'): use the one the user can see, i.e. the active group.
    same = [f for f in fields if f.id.lower() == k or f.id.lower().split("#")[0] == k]
    if same:
        vis = [f for f in same if _live(f)]
        exact = [f for f in same if f.id.lower() == k]
        if len(vis) == 1:
            return vis[0]
        if exact and (not vis or exact[0] in vis):
            return exact[0]
        if vis:
            return vis[0]
    hits = [f for f in fields if f.label and f.label.lower() == k]
    if len(hits) > 1:
        vis = [f for f in hits if _live(f)]
        if len(vis) == 1:
            return vis[0]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise Exception("Label '%s' is ambiguous; use one of ids: %s" % (key, [h.id for h in hits]))
    hits = [f for f in fields if f.label and f.label.lower().startswith(k)]
    if len(hits) == 1:
        return hits[0]
    raise Exception("No field matches '%s'. Fields: %s" % (key, ["%s (%s)" % (f.id, f.label) for f in fields]))


def _commit(root, f):
    """Tab out of the field so TBC parses/validates it like a user entry."""
    if f.tech == "wpf":
        try:
            be = f.target.GetBindingExpression(WC.TextBox.TextProperty)
            if be is not None:
                be.UpdateSource()
        except Exception:
            pass
        # TBC's WPF entry boxes (ClientAreaTextBox) parse when focus leaves them: tab out like the user
        try:
            from System.Windows.Input import TraversalRequest, FocusNavigationDirection, Keyboard
            if not f.target.IsKeyboardFocusWithin:
                f.target.Focus()
            f.target.MoveFocus(TraversalRequest(FocusNavigationDirection.Next))
        except Exception:
            pass
        return
    for c in (f.wrapper, f.target):  # TBC composite controls expose their own validation
        try:
            if hasattr(c, "ValidateInput"):
                c.ValidateInput(True)
                break
        except Exception:
            pass
    try:
        root.SelectNextControl(f.target, True, True, True, True)
    except Exception:
        pass


def _set(root, f, v):
    t = f.target
    if not _enabled(f):
        raise Exception("Field '%s' is disabled" % f.id)
    if f.kind in ("bool", "radio"):
        b = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on", "checked")
        if f.tech == "wpf":
            t.IsChecked = b
            return
        # Click like a user so the panel's own Click/CheckedChanged handlers run (setting .Checked in code
        # can leave the command's internal mode out of sync, e.g. Change Elevation applied 'undefined').
        if f.kind == "radio":
            if not b:
                raise Exception("Can't un-select a radio option directly; select another option instead")
            t.PerformClick()
            if not t.Checked:
                t.Checked = True
            return
        if bool(t.Checked) != b:
            _mouse_click(t, 8, t.Height // 2)  # the check box glyph sits at the left edge
            if bool(t.Checked) != b:
                t.Checked = b
        return
    if f.kind == "number":
        t.Value = Decimal(float(v))
        _commit(root, f)
        return
    if f.kind == "entity":
        serial = _resolve_serial(v)  # raises for a non-existent serial; None for text
        if serial is not None:
            f.wrapper.SetEntity(UInt32(serial), prj)
            return
        # text (e.g. a point ID or a new name): type it like the user would and let TBC parse it
    if f.kind == "text" and _is_numeric_edit(t):
        try:
            t.Value = float(v)
            _commit(root, f)
            return
        except (TypeError, ValueError):
            pass
    if f.kind == "ultra" and hasattr(t, "Checked") and not hasattr(t, "Items"):  # UltraCheckEditor
        b = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on", "checked")
        if bool(t.Checked) != b:
            t.Checked = b
        return
    if f.kind == "ultra" and not hasattr(t, "Items"):  # UltraTextEditor: plain text entry
        try:
            t.Focus()
        except Exception:
            pass
        t.Text = "" if v is None else str(v)
        _commit(root, f)
        return
    if f.kind == "list" and t.GetType().Name == "CheckedListBox" or (f.kind == "list" and hasattr(t, "SetItemChecked")):
        # checkbox list (Select by Layer, quality/type filters): tick the named items like the user, untick the rest
        # only when given {"only": [...]}; a plain string or list ticks those items and leaves others as they are
        items = list(t.Items)
        texts = [_item_text(t, x) for x in items]
        only = isinstance(v, dict) and "only" in v
        want = v["only"] if only else (v if isinstance(v, (list, tuple)) else [v])
        want_l = [str(w).strip().lower() for w in want]
        missing = [w for w in want if str(w).strip().lower() not in [s.strip().lower() for s in texts]]
        if missing:
            raise Exception("%s not in the list '%s'. Options: %s" % (missing, f.id, texts[:MAX_OPTIONS]))
        for i, s in enumerate(texts):
            on = s.strip().lower() in want_l
            if on and not t.GetItemChecked(i):
                t.SetItemChecked(i, True)
            elif only and not on and t.GetItemChecked(i):
                t.SetItemChecked(i, False)
        return
    if f.kind in ("choice", "ultra", "list"):
        items = list(t.Items) if hasattr(t, "Items") else []
        texts = [str(x.DisplayText) if f.kind == "ultra" and hasattr(x, "DisplayText") else _item_text(t, x) for x in items]
        want = str(v).strip().lower()
        idx = next((i for i, s in enumerate(texts) if s.strip().lower() == want), None)
        if idx is None:
            c = [i for i, s in enumerate(texts) if want in s.lower()]
            idx = c[0] if len(c) == 1 else None
        if idx is not None:
            if f.kind == "ultra":
                t.SelectedIndex = idx
            elif f.kind == "list":
                t.SelectedIndex = idx
            else:
                t.SelectedIndex = idx
            _commit(root, f)
            return
        if f.kind == "choice" and f.tech == "winforms" and str(t.DropDownStyle) != "DropDownList":
            t.Focus()
            t.Text = str(v)
            _commit(root, f)
            return
        raise Exception("'%s' is not an option for '%s'. Options: %s" % (v, f.id, texts[:MAX_OPTIONS]))
    # text
    if f.tech == "winforms" and isinstance(v, dict) and "type" in v and isinstance(t, TextBoxBase):
        _type_keys(t, str(v["type"]))  # {"type": "..."}: keystrokes appended at the end, no Enter, no tab-out
        return
    if f.tech == "winforms" and isinstance(v, str) and "\n" in v and isinstance(t, TextBoxBase):
        _type_keys(t, v)  # multi-line command text: type it line by line like the user
        return
    if f.tech == "wpf" and (isinstance(v, int) and not isinstance(v, bool) or isinstance(v, dict) and "serial" in v):
        se = _wpf_ancestor(t, "SelectEntity")
        if se is not None:
            # WPF object picker (Divide Area 'Area to Divide', Insert Segment 'Line' ...): link the object by serial
            serial = _resolve_serial(v)
            se.SetEntity(UInt32(serial), prj)
            return
    ms = _typed_parent(t, f, "MemberSelection")
    if ms is not None and isinstance(v, (list, tuple)):
        # multi-select box ("Selected: N"): a list of serials fills it directly (panels with two such boxes,
        # e.g. Trim/Extend bounding lines + lines to trim, cannot both come from the global selection)
        from System.Collections.Generic import List as GList
        lst = GList[UInt32]()
        for s in v:
            _resolve_serial(int(s))
            lst.Add(UInt32(int(s)))
        ms.SetSelection(prj, lst)
        return
    lr = _typed_parent(t, f, "LeftRightEdit")
    if lr is not None and v is not None:
        # Side to offset (Offset, ...): typed text is shown but the Side enum stays Right; set the enum itself
        import System
        lr.Side = System.Enum.Parse(lr.Side.GetType(), str(v).strip().capitalize())
        return
    ce = _coordinate_edit(t, f)
    if ce is not None and v is not None and str(v).strip():
        # TBC CoordinateEdit (Point one/Corner/Start point ...): setting Text or SetCoordinate in code shows the value
        # but some commands (Three-Point Circle/Rectangle) still say "Pick a point in a Plan View". Real keystrokes
        # plus Enter go through TBC's keyboard input path and work everywhere (point ID or "N,E[,Z]").
        tb = _inner_textbox(ce)
        if tb is not None:
            tb.Focus()
            tb.SelectAll()
            _type_keys(tb, str(v).replace("\n", "") + "\n")
            return
    if f.tech == "wpf" and isinstance(v, str) and v.endswith("\n"):
        # "value\n": type it and press Enter without leaving the box (Quick Line / Outline add one vertex per Enter)
        t.Focus()
        t.Text = v.rstrip("\n")
        _wpf_enter(t)
        return
    try:
        t.Focus()  # WinForms and WPF: enter the box like the user before typing
    except Exception:
        pass
    t.Text = "" if v is None else str(v)
    _commit(root, f)


def _wpf_enter(t):
    """Press Enter once in a WPF element. Only the Preview events are sent: the input manager promotes them to
    KeyDown/KeyUp itself, so sending those too would be a second Enter (which hit the default OK button)."""
    from System.Windows.Input import Keyboard, Key, KeyEventArgs, InputManager
    from System.Windows import PresentationSource
    src = PresentationSource.FromVisual(t)
    for ev in (Keyboard.PreviewKeyDownEvent, Keyboard.PreviewKeyUpEvent):
        e = KeyEventArgs(Keyboard.PrimaryDevice, src, 0, Key.Enter)
        e.RoutedEvent = ev
        InputManager.Current.ProcessInput(e)


def _inner_textbox(c):
    if isinstance(c, TextBoxBase):
        return c
    if not isinstance(c, Control):  # WPF CoordinateEdit (Create Circle/Arc/Rectangle): typed Text already works
        return None
    for k in c.Controls:
        r = _inner_textbox(k)
        if r is not None:
            return r
    return None


def _coordinate_edit(t, f):
    """The Trimble CoordinateEdit behind a field (the control itself, its wrapper or a parent), else None."""
    return _typed_parent(t, f, "CoordinateEdit")


def _wpf_ancestor(t, type_name, depth=8):
    """Nearest WPF visual ancestor (or the element itself) whose class name is `type_name`, else None."""
    try:
        from System.Windows.Media import VisualTreeHelper
        x = t
        for _ in range(depth):
            if x is None:
                return None
            if x.GetType().Name == type_name:
                return x
            x = VisualTreeHelper.GetParent(x)
    except Exception:
        pass
    return None


def _typed_parent(t, f, type_name):
    """The control of class `type_name` behind a field (the control itself, its wrapper or a parent), else None."""
    cands = [getattr(f, "wrapper", None), t]
    try:
        cands += [t.Parent, t.Parent.Parent]
    except Exception:
        pass
    for c in cands:
        try:
            if c is not None and c.GetType().Name == type_name:
                return c
        except Exception:
            pass
    return None


def _is_numeric_edit(t):
    """TBC NumericEdit-style boxes ignore typed Text; their Double `Value` must be set."""
    try:
        p = t.GetType().GetProperty("Value")
        return p is not None and p.CanWrite and p.PropertyType.Name == "Double"
    except Exception:
        return False


def _resolve_serial(v):
    """Serial number for a picker field, ONLY when the caller passed a real number ({"serial": n} or an int).
    Strings are never treated as serials: '4700486' is a point ID typed by the user, not object #4700486.
    (Treating it as a serial linked TBC to a non-existent object and crashed it during Compute, 2026-10-13.)
    The serial must exist, otherwise refuse."""
    if isinstance(v, dict):
        v = v.get("serial")
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    o = prj.Concordance.Lookup(UInt32(v)) if v > 0 else None
    if o is None:
        raise Exception("No object with serial %s in the project" % v)
    return int(v)


def _find_button(buttons, key):
    k = _clean(key).lower()
    for b in buttons:
        if (_name_of(b) or "").lower() == k:
            return b
    hits = [b for b in buttons if (_btn_text(b) or "").lower() == k]
    if hits:
        return hits[-1]  # the command's own buttons come after the frame's
    raise Exception("No button '%s'. Buttons: %s" % (key, [_btn_desc(b) for b in buttons]))


def _press(b):
    """Press asynchronously so a modal popup can't block the bridge."""
    def go():
        try:
            if HAVE_WPF and isinstance(b, DependencyObject):
                ButtonAutomationPeer(b).GetPattern(PatternInterface.Invoke).Invoke()
            else:
                b.PerformClick()
        except Exception:
            pass
    TrimbleOffice.TheOffice.MainForm.BeginInvoke(Action(go))


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------
def state(args):
    scope = args.get("scope") or "command"
    out = {"modal_dialogs": [{"index": i, "title": _title(f), "type": f.GetType().FullName} for i, f in enumerate(_modal_forms())]}
    ch, cmd = _cmd()
    out["open_command"] = str(cmd.Key) if cmd is not None else None
    out["panes"] = [{"title": t, "open": not p.Closed} for t, p in _dock_panes()]
    if scope == "command" and cmd is None:
        return out
    root, c = _root(scope)
    fields, buttons, texts = _collect(root, bool(args.get("include_hidden")))
    if c is not None:
        out["command"] = {"key": str(c.Key), "caption": _clean(c.Caption)}
    elif scope.startswith("pane:"):
        out["pane"] = {"title": scope[5:], "control": root.GetType().FullName}
        out["grids"] = _grids(root)
    else:
        out["dialog"] = {"title": _title(root)}
    out["fields"] = [_describe(f) for f in fields]
    out["buttons"] = [_btn_desc(b) for b in buttons]
    tb = _tabs(root)
    if tb:
        out["tabs"] = tb  # select one with command_ui_click button=<tab name>
    if args.get("include_text", True):
        tx = []
        for t in texts:
            try:
                if HAVE_WPF and isinstance(t, DependencyObject):
                    s = _clean(t.Text) if isinstance(t, WC.TextBlock) else _wpf_text(t.Content)
                else:
                    s = _clean(t.Text)
            except Exception:
                s = None
            if s and s not in [f.label for f in fields]:
                tx.append(s)
        out["texts"] = tx[:80]
    return out


def fill(args):
    root, c = _root(args.get("scope"))
    fields, buttons, _ = _collect(root, True)
    done, errors = [], []
    vals = args.get("values") or []
    pairs = vals.items() if isinstance(vals, dict) else [(p[0], p[1]) for p in vals]  # ordered list preferred
    for k, v in pairs:
        try:
            f = _match(fields, k)
            _set(root, f, v)
            done.append({"field": f.id, "label": f.label, "requested": v, "now": _value(f), "status": _status(f)})
            if f.kind in ("radio", "bool", "choice", "ultra", "entity"):
                # options can rebuild parts of the panel (e.g. Double Proportioning's North/East/South/West swap the
                # input boxes): re-read the panel so later values go into the live controls, not stale ones
                fields, buttons, _ = _collect(root, True)
        except Exception as ex:
            errors.append({"field": k, "error": str(ex)})
            if args.get("stop_on_error", True):
                break
    # Re-read every field we set: a later entry can make TBC reset an earlier one.
    fields, buttons, _ = _collect(root, True)
    for d in done:
        try:
            f = _match(fields, d["field"])
            d["now"] = _value(f)
            d["status"] = _status(f)
            if str(d["now"]).strip() == "" and str(d["requested"]).strip() != "":
                d["warning"] = "field is empty after filling; TBC may have rejected or reset it"
        except Exception:
            pass
    out = {"set": done, "errors": errors}
    if args.get("press") and not errors:
        b = _find_button(buttons, args["press"])
        _press(b)
        out["pressed"] = _btn_text(b)
    return out


def _tab_controls(root):
    out = []

    def walk(c):
        tn = c.GetType().Name
        if tn in ("UltraTabControl", "TabControl"):
            out.append(c)
        for k in c.Controls:
            walk(k)
    if not (HAVE_WPF and isinstance(root, DependencyObject)):
        walk(root)
    return out


def _tabs(root):
    res = []
    for tc in _tab_controls(root):
        try:
            if tc.GetType().Name == "UltraTabControl":
                res.append({"tabs": [_clean(t.Text) for t in tc.Tabs], "selected": _clean(tc.SelectedTab.Text) if tc.SelectedTab else None})
            else:
                res.append({"tabs": [_clean(t.Text) for t in tc.TabPages], "selected": _clean(tc.SelectedTab.Text) if tc.SelectedTab else None})
        except Exception:
            pass
    return res


def _select_tab(root, name):
    k = _clean(name).lower()
    for tc in _tab_controls(root):
        tabs = list(tc.Tabs) if tc.GetType().Name == "UltraTabControl" else list(tc.TabPages)
        for t in tabs:
            if (_clean(t.Text) or "").lower() == k:
                tc.SelectedTab = t
                return _clean(t.Text)
    return None


def click(args):
    root, c = _root(args.get("scope"))
    _, buttons, _ = _collect(root, False)
    try:
        b = _find_button(buttons, args["button"])
    except Exception:
        t = _select_tab(root, args["button"])  # clicking a tab header selects that tab
        if t:
            return {"selected_tab": t}
        raise
    _press(b)
    return {"pressed": _btn_text(b)}


def close(args):
    ch, cmd = _cmd()
    if cmd is None:
        return {"closed": None}
    k = str(cmd.Key)
    if args.get("all"):
        ch.CloseAll()
    else:
        ch.CloseCommand(cmd)
    return {"closed": k}


def license(args):
    """Silently check whether commands are licensed (no TBC license popup). keys -> {licensed, needs}."""
    from System import Array
    from Trimble.Vce.Core import Server
    from Trimble.Vce.License import Feature
    srv = Server.TheServer
    cl = TrimbleOffice.TheOffice.CommandProcessor.CommandList
    out = {}
    for k in args.get("keys") or []:
        kk = str(k).lower()
        if not cl.ContainsKey(kk):
            out[k] = {"exists": False}
            continue
        try:
            codes = list(cl[kk].LicenseCodes or [])
        except Exception:
            codes = []
        try:
            ok = True if not codes else bool(srv.CanUseFeature(Array[Feature](codes)))
        except Exception as ex:
            ok = None
        out[k] = {"exists": True, "licensed": ok, "needs_any_of": [str(c) for c in codes]}
    return out


def close_dialog(args):
    """Close a TBC modal dialog the way the title-bar X does (no button is pressed)."""
    forms = _modal_forms()
    i = int(args.get("index", 0))
    if i >= len(forms):
        return {"closed": None}
    f = forms[i]
    title = _title(f)
    TrimbleOffice.TheOffice.MainForm.BeginInvoke(Action(f.Close))
    return {"closed": title}


def forms(args):
    """Open top-level/MDI windows other than the main window: [{id, title, type, mdi}] (id = handle)."""
    out = []
    mf = TrimbleOffice.TheOffice.MainForm
    for f in Application.OpenForms:
        try:
            if f is mf or not f.Visible:
                continue
            out.append({"id": int(f.Handle.ToInt64()), "title": str(f.Text), "type": f.GetType().Name,
                        "mdi": bool(f.IsMdiChild), "modal": bool(f.Modal)})
        except Exception:
            pass
    return out


def close_forms(args):
    """Close the given (non-modal) windows by handle id, like their X button."""
    ids = set(int(i) for i in args.get("ids") or [])
    closed = []
    for f in list(Application.OpenForms):
        try:
            if int(f.Handle.ToInt64()) in ids and f is not TrimbleOffice.TheOffice.MainForm and not f.Modal:
                closed.append(str(f.Text))
                TrimbleOffice.TheOffice.MainForm.BeginInvoke(Action(f.Close))
        except Exception:
            pass
    return {"closed": closed}


def editor_button(args):
    """Click an Infragistics editor's built-in button (e.g. the '...' Browse button of a Source file box) with a
    genuine in-process mouse click, asynchronously (it usually opens a modal file dialog)."""
    root, _ = _root(args.get("scope"))
    fields, _, _ = _collect(root, True)
    f = _match(fields, args["field"])
    ed = f.wrapper
    btns = list(ed.ButtonsRight) + list(ed.ButtonsLeft)
    if not btns:
        raise Exception("Field '%s' has no editor buttons" % f.id)
    b = btns[int(args.get("index", 0))]
    el = None
    try:
        el = b.GetUIElement(ed.UIElement)
    except Exception:
        el = None
    if el is not None:
        rc = el.Rect
        x, y = rc.X + rc.Width // 2, rc.Y + rc.Height // 2
    else:
        x, y = ed.Width - 8, ed.Height // 2  # editor buttons sit at the right edge
    TrimbleOffice.TheOffice.MainForm.BeginInvoke(Action(lambda: _mouse_click(ed, x, y)))
    return {"clicked_editor_button": str(b.Key), "field": f.id}


result = {"forms": forms, "close_forms": close_forms, "editor_button": editor_button,
          "state": state, "fill": fill, "click": click, "close": close, "license": license,
          "close_dialog": close_dialog, "grid_read": grid_read, "grid_set": grid_set,
          "grid_cell_point": grid_cell_point, "grid_click": grid_click}[ACTION](ARGS)

