# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# IronPython 3.4 code executed INSIDE TBC by the MCP server (via the bridge's execute_python).
# The server prepends:  ACTION = "<name>"; ARGS = {...}
# and reads `result`. Keep IronPython 3.4 compatible (no f-strings).
#
# Drives TBC command panels (WinForms, plus basic WPF for macro panels): inspect fields with
# their on-screen labels, fill them like a user would (type + tab out so TBC validates),
# press buttons, and list/handle modal dialogs.
"""command_ui.py - the "panel engine" of TBC MCP.

WHAT IT IS
    IronPython 3.4 source that the MCP server (mcp_server/tbc_mcp_server.py) sends INTO Trimble Business Center on
    every call. It reads TBC's command panels, popups and docked panes (WinForms and WPF), fills their fields the way
    a user would, presses buttons, and reads/edits the grids (tables) inside them. It never talks to the network and
    never touches the project database directly, except to look up objects by serial number (prj.Concordance) and
    to link objects into picker fields, which is what the panels themselves do when the user picks something.

HOW IT IS INVOKED
    run_ipy("command_ui", action, args) in the server reads this file (utf-8-sig, so a BOM is tolerated) and
    prepends three lines:
        ACTION = '<action name>'
        import json as _j
        ARGS = _j.loads('<the args as JSON>')
    It sends the result to the bridge macro (tbc_macro/TbcMcpBridge.py) as an `execute_python` request with
    transaction=False (run_ipy's default; no command_ui caller asks for a transaction, so nothing here becomes an
    undo step of its own). The bridge exec()s the code on TBC's UI thread (Dispatcher.Invoke at Background
    priority) in a namespace that already contains, among others:
        clr, prj / project (the open TBC project or None), wv (its world view), TrimbleOffice (TBC's application
        object), bridge, jsonable.
    `TrimbleOffice` and `prj` are used below without being imported: they come from that namespace.
    The last statement of this file looks ACTION up in a dict of action functions, calls it with ARGS and stores the
    return value in `result`. The bridge converts `result` with its jsonable() helper and sends it back. Any exception
    raised here becomes {"ok": false, "error": ..., "traceback": ...} in the bridge and a BridgeError in the server,
    so raising with a clear message is the normal way to refuse something. An unknown ACTION raises KeyError.
    The file is loaded fresh on every call (no macro reinstall needed after edits) and keeps NO state between
    calls: every call walks the live control tree again.

ACTIONS (ARGS -> result)
    state         {scope, include_hidden=False, include_text=True}
                  -> {"modal_dialogs": [{index, title, type}], "open_command": key or None,
                      "panes": [{title, open}],
                      and, when the scope resolves to something:
                      "command": {key, caption} | "pane": {title, control} plus "grids" | "dialog": {title},
                      "fields": [field description], "buttons": [{id, text, enabled?}],
                      "tabs": [{tabs, selected}] (only if any), "texts": [static label texts] (if include_text)}
                  A field description is {id, label, kind, value} plus, only when relevant, enabled=False,
                  visible=False, options=[...], status="<TBC status message>", control="<class name>".
    fill          {scope, values, press=None, stop_on_error=True}
                  values = ordered list of [label_or_id, value] pairs (preferred) or a dict.
                  -> {"set": [{field, label, requested, now, status, warning?}], "errors": [{field, error}],
                      "pressed": button text (only if press was given and there were no errors)}
    click         {scope, button}  -> {"pressed": text} or {"selected_tab": name} (a tab header was named)
    close         {all=False}      -> {"closed": command key or None}
    license       {keys: [...]}    -> {key: {"exists": False} | {"exists": True, "licensed": True/False/None,
                                                                  "needs_any_of": [feature codes]}}
    close_dialog  {index=0}        -> {"closed": dialog title or None}
    forms         {}               -> [{id (window handle), title, type, mdi, modal}]   (used by the test suites)
    close_forms   {ids: [...]}     -> {"closed": [titles]}                              (used by the test suites)
    editor_button {scope, field, index=0} -> {"clicked_editor_button": key, "field": id}  (no MCP tool calls it)
    grid_read     {scope, grid, where, limit=200} -> {grid, kind?, columns, row_count, rows (each with "_row")}
    grid_set      {scope, grid, row, column, value} -> {row, column, now}
    grid_cell_point {scope, grid, row, column} -> {hwnd, x, y, row, row_values, column}
    grid_click    {scope, grid, row, column} -> grid_cell_point's result + {"temporarily_hidden_columns": [...]}

SCOPES (where to look; see _root)
    "command" (default) the open command panel (CommandHost.TopCommand.CommandUI)
    "dialog" / "dialog:<i>" the i-th popup: visible modal WinForms forms first, then visible WPF windows
    "pane:<title>"      a docked/floating TBC pane, e.g. "pane:Layer Manager" (title compared case-insensitively)

WINFORMS VS WPF
    Most TBC panels are WinForms. Their control tree is walked through Control.Controls (_collect). WPF content
    is reached in two ways: hosted inside a WinForms tree through an ElementHost (macro panels; also the WPF boxes
    and pickers of some TBC commands, e.g. Divide Area's 'Area to Divide'), or as a root that is itself a WPF element
    (a separate WPF Window: some TBC popups, e.g. "Feature Library Missing"). WPF trees are walked
    through LogicalTreeHelper (_walk_wpf). WPF support is optional: if the WPF assemblies cannot be referenced,
    HAVE_WPF is False and only WinForms is handled. Grids and tab controls are only looked for in WinForms trees.

HOW FIELDS ARE IDENTIFIED
    kind   what the field holds: text, entity (object picker), bool (check box), radio, choice (drop-down),
           number (NumericUpDown), list (list box / checkbox list), ultra (Infragistics editor).
    label  WinForms: a check box's / radio button's own text, otherwise the nearest visible Label to the left of
           (or above) the field, found by screen geometry (_label_in). WPF: the text of the closest preceding
           TextBlock/Label in tree order.
    id     the control's Name (the composite wrapper's, else the inner control's), else the label or kind with
           spaces replaced by "_"; repeats get "#2", "#3" ... in tree order. Ids are recomputed on every call.
    A key passed to fill/editor_button is matched by id first, then by exact label, then by a unique label prefix,
    preferring the field the user can currently see when several share a name (_match).

HOW VALUES ARE ENTERED (_set)
    The aim is "like a user": enter the box, set the value, then leave it with Tab (_commit) so TBC parses and
    validates the entry exactly as it does for typed input. Special cases, each found on TBC 2026.10:
      - check boxes get a genuine in-process mouse click; radio buttons PerformClick (setting Checked in code left
        some commands' internal mode out of sync);
      - TBC coordinate boxes (CoordinateEdit) and multi-line command boxes get real keystrokes (WM_CHAR + Enter)
        because a value set in code was shown but not used;
      - numeric boxes with a Double `Value` get that Value (they ignore typed Text);
      - object pickers link an object only for an explicit integer serial or {"serial": n} that exists; strings are
        always typed as text (a point ID is not a serial);
      - multi-select boxes ("Selected: N") take a list of serials; Left/Right boxes get their Side enum set;
      - drop-downs only accept one of their options (exact, else a unique substring); editable WinForms combo
        boxes also accept free text.

SAFETY RULES ENFORCED HERE
    - Buttons, grid clicks, editor-button clicks and window closes are queued with MainForm.BeginInvoke, so they
      run after this bridge call has returned: a modal popup they open can never block the bridge.
    - Disabled fields and read-only grid columns are refused; a value that is not a drop-down option is refused.
    - Strings are never treated as object serials, and a serial must exist in the project before it is linked
      (a non-existent serial crashed TBC during Compute on 2026-10-13).
    - Grid rows must match exactly one row; grid_click re-checks the row's values just before clicking.
    - fill stops at the first error by default and never presses its button when any field failed.
    - license checks licensing silently, without opening the command (so no TBC license popup appears).
    - close_dialog closes a popup like its title-bar X; it never presses a button. close_forms never closes the main
      window or a modal popup.
    The other guardrails (license check before opening, pacing, waiting for Compute Project, only pressing safe
    popup buttons, field-order guards, settle time) live in tbc_mcp_server.py, not here.
"""
# ---------------------------------------------------------------------------
# Imports and WPF availability
# ---------------------------------------------------------------------------
import clr
clr.AddReference("System.Windows.Forms")
# Action: delegate type for MainForm.BeginInvoke; Decimal: NumericUpDown.Value's type; UInt32: TBC serial numbers.
from System import Action, Decimal, UInt32
from System.Windows.Forms import (Control, TextBoxBase, ComboBox, CheckBox, RadioButton, ButtonBase, Label,
                                  NumericUpDown, Application, Form, ListBox)

# WPF is optional: PresentationFramework/PresentationCore hold the WPF controls, tree helpers, input and automation
# peers; WindowsFormsIntegration holds ElementHost (WPF content inside a WinForms panel). If any of it fails to load,
# HAVE_WPF is False and every WPF branch below is skipped (all of them test HAVE_WPF first).
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

# Cap on how many drop-down / list options are reported (state, error messages), to keep replies small.
# Matching in _set still searches every item, not just the first MAX_OPTIONS.
MAX_OPTIONS = 60


# ---------------------------------------------------------------------------
# Small helpers: text cleanup, the open command, popups and docked panes
# ---------------------------------------------------------------------------
def _clean(t):
    """Normalise an on-screen caption for display and matching.

    Removes every '&' (the WinForms access-key marker, e.g. '&OK' shows as 'OK'), surrounding whitespace and one
    trailing ':' (labels such as 'Point ID:'). Returns None for None or for a caption that ends up empty, so callers
    can use `_clean(x) or fallback`. Note: a literal '&' in a caption is removed too.
    """
    if t is None:
        return None
    t = str(t).replace("&", "").strip()
    if t.endswith(":"):
        t = t[:-1].strip()
    return t or None


def _cmd():
    """Return (CommandHost, active command) of TBC's main window.

    CommandHost manages the command panels; TopCommand is the command whose panel is on top, or None when no
    command is open. Read-only, no side effects. `TrimbleOffice` comes from the bridge's namespace.
    """
    ch = TrimbleOffice.TheOffice.MainForm.CommandHost
    return ch, ch.TopCommand


def _wpf_windows():
    """Visible WPF windows on this thread (TBC shows some popups, e.g. 'Feature Library Missing', as WPF).

    WPF windows are not in WinForms' Application.OpenForms, so they are found through
    PresentationSource.CurrentSources (every WPF presentation source of the calling thread, i.e. TBC's UI thread)
    and kept when their RootVisual is a visible Window. Before this existed the dialog tools missed such popups and
    left them open (lesson 14). Returns [Window]; [] without WPF. Read-only.
    Note: every visible WPF window is returned, modal or not, so _modal_forms treats them all as popups.
    """
    out = []
    if not HAVE_WPF:
        return out
    try:
        from System.Windows import PresentationSource, Window
        for src in PresentationSource.CurrentSources:
            # each source is guarded separately: one disposed/odd source must not hide the other windows
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
    """Popups/dialogs: modal WinForms forms plus visible WPF windows.

    The ORDER of this list defines the dialog index used everywhere: scope 'dialog:<i>' (_root), close_dialog's
    `index` and state's modal_dialogs[].index. WinForms forms come first, in Application.OpenForms order, then the
    WPF windows. Indexes are only valid until a popup opens or closes, which is why the server re-reads the list
    (dialogs_snapshot) right before it acts. Returns [Form or Window]. Read-only.
    """
    out = []
    for f in Application.OpenForms:
        try:
            if f.Visible and f.Modal:
                out.append(f)
        except Exception:
            pass
    return out + _wpf_windows()


def _title(f):
    """Title bar text of a popup: Window.Title for WPF (any DependencyObject), Form.Text for WinForms; '' on error."""
    try:
        return str(f.Title) if HAVE_WPF and isinstance(f, DependencyObject) else str(f.Text)
    except Exception:
        return ""


def _dock_panes():
    """TBC's docked/floating panes (Layer Manager, Properties, Project Explorer, ...): [(title, pane)].

    TBC's panes are managed by an Infragistics UltraDockManager held in a field of the main form. The code finds it
    by reflection: every instance field (public AND non-public) whose type is named 'UltraDockManager', so it does
    not depend on the field's name. Each of its ControlPanes is returned with its trimmed caption. A pane object has
    .Closed (True while the pane is hidden/closed) and .Control (the WinForms control shown in it), which _root uses
    for scope 'pane:<title>'. Read-only.
    """
    from System.Reflection import BindingFlags
    mf = TrimbleOffice.TheOffice.MainForm
    out = []
    for fi in mf.GetType().GetFields(BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public):
        if fi.FieldType.Name != "UltraDockManager":  # compared by name: no reference to the Infragistics DLL needed
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


# ---------------------------------------------------------------------------
# Grids: discovery
# ---------------------------------------------------------------------------
def _find_grids(root):
    """Every grid (table) under a WinForms root, in tree order: [DataGridView or UltraGrid].

    Two grid families exist in TBC: the standard WinForms DataGridView (e.g. Layer Manager, Explode Points'
    pointList) and Infragistics UltraGrid, matched by class name containing 'UltraGrid' so subclasses such as
    DisposingUltraGrid (survey spreadsheet views, lesson 38) count too. The walk does not descend into a grid.
    WPF roots return [] (WPF grids are not supported). Includes hidden grids. Read-only.
    """
    from System.Windows.Forms import DataGridView
    out = []

    def walk(c):
        """Depth-first search of c.Controls, collecting grids into `out`."""
        if isinstance(c, DataGridView) or "UltraGrid" in c.GetType().Name:
            out.append(c)
            return
        for k in c.Controls:
            walk(k)
    if not (HAVE_WPF and isinstance(root, DependencyObject)):
        walk(root)
    return out


# ---------------------------------------------------------------------------
# Infragistics UltraGrid support (TBC's merge/explode/source lists, spreadsheets)
# An UltraGrid is hierarchical: rows belong to "bands" (Band.Key), and a row can own child bands with their own
# rows. Columns are addressed by Column.Key. The helpers below flatten that into a simple row list.
# ---------------------------------------------------------------------------
def _is_ultra(g):
    """True for an Infragistics UltraGrid (or subclass, e.g. DisposingUltraGrid), False for a DataGridView."""
    return "UltraGrid" in g.GetType().Name


def _u_rows(g):
    """All rows of an UltraGrid, flattened depth-first: each row followed by the rows of its child bands.

    Returns [UltraGridRow] (the band of a row is r.Band.Key; earlier versions of this docstring said
    [(row, band_key)], but only rows are returned). The code does not check whether a parent row is expanded on
    screen, so collapsed children are included too. The list index is the "_row" number reported by grid_read and
    accepted as an int `row` by grid_set. Read-only.
    """
    out = []

    def add(rows):
        """Append rows and, recursively, the rows of their child bands."""
        for r in rows:
            out.append(r)
            try:
                if r.ChildBands is not None:
                    for cb in r.ChildBands:
                        add(cb.Rows)
            except Exception:
                pass  # rows without child-band support: just skip their children
    add(g.Rows)
    return out


def _u_cols(g):
    """Visible columns of every band of an UltraGrid.

    Returns [{"band": band key, "name": column key, "header": cleaned caption, "type": .NET data type name}].
    "type" is e.g. 'Boolean' for check box columns (_u_set relies on that). Hidden columns are left out. Read-only.
    """
    res = []
    for b in g.DisplayLayout.Bands:
        for c in b.Columns:
            if not c.Hidden:
                res.append({"band": str(b.Key), "name": str(c.Key), "header": _clean(c.Header.Caption), "type": str(c.DataType.Name)})
    return res


def _u_cell_val(cell):
    """JSON-friendly value of an UltraGrid cell (see _cell_text)."""
    return _cell_text(cell.Value)


def _u_row_dict(r):
    """One UltraGrid row as {"_band": band key, <column key>: value, ...} for its visible columns. Read-only."""
    d = {"_band": str(r.Band.Key)}
    for c in r.Cells:
        if not c.Column.Hidden:
            d[str(c.Column.Key)] = _u_cell_val(c)
    return d


def _u_match(g, match):
    """Find exactly one UltraGrid row.

    match is either an int (index into the flattened _u_rows list, i.e. a "_row" from grid_read) or a dict
    {column key: value, ...} where every pair must equal the cell text (trimmed, case-insensitive); the special key
    "_band" compares the row's band key instead. Unlike the DataGridView path (_col), keys here are column KEYS
    only, not header captions. Raises unless exactly one row matches, so an ambiguous match never edits the wrong
    row. Read-only.
    """
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
                # this row's band has no such column (rows of other bands): not a match
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
    Setting cell.Value directly, a mouse click or Space did NOT reach TBC's Merge Points logic; this does.

    g: the UltraGrid; r: the row (from _u_match); col: column key; v: new value (bool or truthy string for Boolean
    columns: '1', 'true', 'yes', 'on'; anything else is assigned to cell.Value as is).
    Returns the cell's value afterwards (via _cell_text).
    Side effects: expands the row's parent rows, gives the grid keyboard focus, makes the row/cell active (the
    selection highlight moves), and commits the change to the grid's data source (UpdateData).
    Verified for Merge Points' 'Included' column (lesson 49).
    """
    from System import Enum
    # UltraGridAction is Infragistics' enum of grid commands (EnterEditMode, ToggleCheckbox, ...). It is fetched by
    # name from the assembly that defines the grid's BASE class, so this module needs no clr.AddReference to
    # Infragistics. That base class is UltraGrid itself when g is a subclass (e.g. DisposingUltraGrid). For a plain,
    # non-subclassed UltraGrid the base class would be a different Infragistics type; whether its assembly also
    # holds UltraGridAction is not verified (if not, GetType returns None and Enum.Parse fails).
    UGA = g.GetType().BaseType.Assembly.GetType("Infragistics.Win.UltraWinGrid.UltraGridAction")
    act = lambda name: g.PerformAction(Enum.Parse(UGA, name))
    try:
        # expand every ancestor row so a child-band row can be activated
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
            # toggle only when needed, the way a user ticks the box; a direct cell.Value write was ignored by TBC
            act("ToggleCheckbox")
    else:
        cell.Value = v
    act("ExitEditMode")
    try:
        g.UpdateData()  # push the edited cell into the grid's data source now
    except Exception:
        pass
    return _u_cell_val(cell)


# ---------------------------------------------------------------------------
# DataGridView support (standard WinForms grids, e.g. Layer Manager) and shared cell formatting
# ---------------------------------------------------------------------------
def _cell_text(v):
    """Turn a grid cell value into something JSON-friendly and comparable.

    System.Drawing.Color (colour columns) -> '#RRGGBB'; Bitmap/Image/Icon (icon columns) -> '[image]'; bool stays
    bool; None stays None; everything else -> str(). Used for both grid families.
    """
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
    """Visible DataGridView columns: [{"name", "header", "type", "read_only"}].

    "type" is the column class name without the 'DataGridView' prefix, e.g. 'TextBoxColumn', 'CheckBoxColumn',
    'ComboBoxColumn', 'ImageColumn'. The server's ui_grid relies on 'CheckBoxColumn' to switch to a real click,
    because checkbox cells only reach TBC's model through a click (lesson 2).
    """
    return [{"name": str(c.Name), "header": _clean(c.HeaderText), "type": c.GetType().Name.replace("DataGridView", ""),
             "read_only": bool(c.ReadOnly)} for c in g.Columns if c.Visible]


def _grids(root):
    """Summary of every grid under root for `state` (pane scopes): [{"grid": name, "kind"?, "rows", "columns"}].

    UltraGrids are marked kind='UltraGrid' and count all flattened rows; DataGridViews report RowCount.
    """
    out = []
    for g in _find_grids(root):
        if _is_ultra(g):
            out.append({"grid": str(g.Name), "kind": "UltraGrid", "rows": len(_u_rows(g)), "columns": _u_cols(g)})
        else:
            out.append({"grid": str(g.Name), "rows": g.RowCount, "columns": _grid_cols(g)})
    return out


def _grid(root, name):
    """The grid called `name` (control Name, case-insensitive) under root, or the first grid when name is empty.

    Raises when the root has no grid or no grid of that name (the message lists the available names).
    """
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
    """DataGridView column whose Name or cleaned header text equals key (case-insensitive).

    Searches all columns, hidden ones included. Raises with the list of (name, header) pairs when nothing matches.
    """
    k = str(key).strip().lower()
    for c in g.Columns:
        if str(c.Name).lower() == k or (_clean(c.HeaderText) or "").lower() == k:
            return c
    raise Exception("No column '%s'. Columns: %s" % (key, [(str(c.Name), _clean(c.HeaderText)) for c in g.Columns]))


def _row(g, match):
    """Find exactly one DataGridView row.

    match = {column: value} (all must match, case-insensitive) or an int row index. Columns may be given by name or
    header (_col); values are compared as trimmed text (_cell_text). Raises unless exactly one row matches, so a
    vague match like {"LayerName": "0"} on a list with duplicates can never act on the wrong row. Read-only.
    """
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


# ---------------------------------------------------------------------------
# Grid actions: grid_read, grid_set (and, further down, grid_cell_point, grid_click)
# ---------------------------------------------------------------------------
def grid_read(args):
    """ACTION grid_read: list a grid's columns and rows. Read-only.

    ARGS: scope (see _root), grid (name; default the first grid), where ({column: value} filter, case-insensitive
    exact text match), limit (default 200).
    Returns {"grid", "kind": 'UltraGrid' (UltraGrid only), "columns", "row_count" (ALL rows, before filter/limit),
    "rows": [{column: value, ..., "_row": index}]}. "_row" is the index to pass back as `row` (for an UltraGrid it
    indexes the flattened _u_rows list; for a DataGridView it is Row.Index).
    UltraGrid rows are keyed by column KEY plus "_band"; DataGridView rows by column Name (filters there may use the
    header too, via _col, which raises for an unknown column).
    """
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
    """Edit a cell through the grid's normal editing path (CurrentCell -> BeginEdit -> value -> EndEdit).

    ACTION grid_set. ARGS: scope, grid, row ({column: value} matching exactly one row, or an index), column (name
    or header), value.
    UltraGrid: delegated to _u_set; returns {"row": the row as a dict, "column", "now"}.
    DataGridView: refuses read-only columns; a drop-down cell must be given one of its items (exact text,
    case-insensitive) or the edit is cancelled and an error lists the options; a text cell gets the text typed into
    its editing control; a bool cell gets cell.Value. Returns {"row": index, "column": name, "now": value after}.
    Side effects: moves the grid's current cell (selection) to the edited cell and commits the edit.
    Note: the server's ui_grid does NOT use this for CheckBoxColumn cells of a DataGridView: there it clicks the
    cell (grid_click) because a value set in code only changed the display (lesson 2).
    """
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
        # bool cell given text: accept the usual truthy words, everything else means False
        v = str(v).strip().lower() in ("1", "true", "yes", "on")
    g.CurrentCell = cell
    g.BeginEdit(True)  # True = select all of the cell's text, as when the user starts editing
    ec = g.EditingControl  # the hosted editor (text box / combo box) or None (e.g. check box cells)
    if ec is not None and hasattr(ec, "Items") and not isinstance(v, bool):
        # drop-down cell: only one of its items is accepted
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
        g.CommitEdit(0)  # 0 = no DataGridViewDataErrorContexts flags; pushes the value to the data source
    except Exception:
        pass
    return {"row": r.Index, "column": str(c.Name), "now": _cell_text(r.Cells[c.Index].Value)}


def _mouse_click(ctrl, x, y):
    """Feed genuine mouse messages (move, down, up) into a control's own window procedure, in-process.
    The control handles them exactly like a real click; Windows' cross-process input filtering can't drop them.

    ctrl: a WinForms Control; x, y: CLIENT coordinates (pixels from the control's top-left corner).
    Why: window messages posted from the MCP server's own process did not reach TBC's controls (probably Windows
    UIPI, lesson 3), and setting values in code did not run TBC's click logic (grid check boxes, lesson 2).
    The messages are delivered SYNCHRONOUSLY: the control's click handlers run inside this call. Callers whose click
    may open a modal popup (grid_click, editor_button) therefore wrap it in MainForm.BeginInvoke.
    Side effects: whatever a click on that point does; the real mouse cursor does not move.
    """
    from System import IntPtr, Array, Object
    from System.Windows.Forms import Message
    from System.Reflection import BindingFlags
    # Control.WndProc is protected, so it is fetched by reflection (non-public instance method) and invoked directly
    wndproc = clr.GetClrType(Control).GetMethod("WndProc", BindingFlags.Instance | BindingFlags.NonPublic)
    # lParam of a mouse message packs the client point: x in the low 16 bits, y in the high 16 bits
    lp = IntPtr(((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF))
    # wParam carries the mouse-button state: 1 = MK_LBUTTON (left button down) for the button-down message
    for msg, wp in ((0x0200, 0), (0x0201, 1), (0x0202, 0)):  # WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP
        m = Message.Create(ctrl.Handle, msg, IntPtr(wp), lp)
        wndproc.Invoke(ctrl, Array[Object]([m]))


def _fit_column(g, c):
    """Make column c visible WITHOUT horizontal scrolling (a scrolled grid swallowed Layer Manager's red-X click):
    temporarily hide other non-frozen columns (display only), returning the list to restore afterwards.

    g: a DataGridView; c: one of its columns. Returns [columns hidden here]; the caller MUST set them Visible again
    (grid_click does so after its click). Lesson 21: the red X stopped responding to automated clicks when the pane
    was too narrow for the Delete column and the grid was scrolled horizontally.
    Side effects: resets the horizontal scroll to the left edge; hides columns (column.Visible only affects the
    display, not the data). Columns are hidden from the right-most one leftwards, one at a time, until c is fully
    displayed; frozen columns, already hidden columns, c itself and a column named 'LayerName' (Layer Manager's
    layer-name column) are never hidden.
    """
    hidden = []
    g.HorizontalScrollingOffset = 0
    # "fully displayed": the displayed cell rectangle is (within 1 px) as wide as the column. Row -1 = the header
    # row, used when the grid has no rows.
    if c.Displayed and g.GetCellDisplayRectangle(c.Index, 0 if g.RowCount else -1, False).Width >= c.Width - 1:
        return hidden
    for k in reversed(list(g.Columns)):
        if k.Index == c.Index or k.Frozen or not k.Visible or k.Name in ("LayerName",):
            continue
        k.Visible = False
        hidden.append(k)
        g.PerformLayout()  # re-layout now so Displayed / the cell rectangle reflect the hidden column
        # note: unlike the check above, this one always measures row 0 (it assumes the grid has rows)
        if c.Displayed and g.GetCellDisplayRectangle(c.Index, 0, False).Width >= c.Width - 1:
            break
    return hidden


def _type_keys(ctrl, text):
    """Type text into a WinForms control as real keystrokes (WM_KEYDOWN/WM_CHAR/WM_KEYUP via its WndProc), with
    Enter at each line end - for line-by-line command boxes such as Create COGO's 'Line commands' that only parse
    what the user types.

    ctrl: a WinForms text box (TextBoxBase). text: the characters to type; a newline (Windows CRLF is folded into a
    single newline first) becomes a full Enter key press (key down, char, key up), and a backspace character
    becomes a full Backspace key press; every other character is sent as WM_CHAR only (no key down/up).
    Side effects: gives ctrl keyboard focus; puts the caret at the end of the existing text unless the caller has
    selected text (then the typed text replaces the selection, e.g. after SelectAll in the CoordinateEdit path of
    _set); Enter runs whatever the box does on Enter.
    Messages go straight into the control's WndProc in-process, as in _mouse_click, and run synchronously.
    Where it works: TBC CoordinateEdit boxes (typed point ID + Enter, lesson 51). Lesson 32 records that for Create
    COGO's 'Line commands' box, WM_CHAR keystrokes did NOT produce linework (unresolved on 2026.10), despite the
    purpose stated above.
    """
    from System import IntPtr, Array, Object
    from System.Windows.Forms import Message
    from System.Reflection import BindingFlags
    wndproc = clr.GetClrType(Control).GetMethod("WndProc", BindingFlags.Instance | BindingFlags.NonPublic)

    def send(msg, wp):
        """Deliver one keyboard message (msg, wParam = key or character code, lParam 0) to ctrl's WndProc."""
        wndproc.Invoke(ctrl, Array[Object]([Message.Create(ctrl.Handle, msg, IntPtr(wp), IntPtr(0))]))
    ctrl.Focus()
    try:
        if ctrl.SelectionLength == 0:  # append, unless the caller selected text to replace
            ctrl.SelectionStart = len(ctrl.Text or "")
    except Exception:
        pass
    # message ids: 0x0100 WM_KEYDOWN, 0x0101 WM_KEYUP, 0x0102 WM_CHAR; key codes: 0x08 VK_BACK, 0x0D VK_RETURN
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
            send(0x0102, ord(ch))  # WM_CHAR with the character code: what a text box inserts on a key press


def grid_click(args):
    """ACTION grid_click: a genuine left click on one DataGridView cell, e.g. Layer Manager's red-X Delete column
    or a check box cell whose change only reaches TBC through a click (lesson 2).

    ARGS: scope, grid, row ({column: value} matching exactly one row, or an index), column.
    Steps: fit the column on screen without horizontal scrolling (_fit_column), scroll the row into view and compute
    the cell centre (grid_cell_point), re-check the row's values, then QUEUE the click with MainForm.BeginInvoke and
    return at once. The click therefore runs after this bridge call has returned, so a confirmation popup it opens
    cannot block the bridge; the server then waits and reports popups (ui_after). Columns hidden by _fit_column are
    made visible again inside the queued callback, after the click. Errors during the click itself are swallowed:
    the server re-reads the grid to see whether anything changed.
    Returns grid_cell_point's result plus "temporarily_hidden_columns": [names].
    DataGridView only (uses _col/_row and DataGridView APIs); there is no UltraGrid click.
    The server's ui_grid calls grid_cell_point first and waits 0.8 s before calling this: a click in the same
    instant as the scroll only selected the cell, and the red X did nothing.
    """
    root, _ = _root(args.get("scope"))
    g = _grid(root, args.get("grid"))
    c = _col(g, args["column"])
    hidden = _fit_column(g, c)
    pt = grid_cell_point(args)
    r = g.Rows[pt["row"]]
    # re-verify the row identity right before clicking
    for k, v in (args["row"].items() if isinstance(args["row"], dict) else []):
        if str(_cell_text(r.Cells[_col(g, k).Index].Value)).lower() != str(v).lower():
            # note: columns hidden by _fit_column above are not restored on this path
            raise Exception("Row moved before click; aborted")
    def go():
        """Queued on the UI thread: click the cell centre, then restore the temporarily hidden columns."""
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
    deliver a genuine mouse click (exactly like the user clicking it).

    ACTION grid_cell_point (also called by grid_click). ARGS: scope, grid, row, column (as for grid_click).
    Returns {"hwnd": grid window handle, "x", "y": client point of the cell centre, "row": row index,
    "row_values": {column: value} of the visible non-image columns (identifies the row in the reply),
    "column": column name}.
    History: the hwnd/x/y were meant for a click posted from the server process (post_click in the server); posted
    messages did not reach TBC (lesson 3), so grid_click now clicks x/y in-process. The server's ui_grid action=click
    still calls this first on its own, to scroll the cell into view and let the grid redraw before clicking.
    Side effects: scrolls the grid vertically and/or horizontally. Raises when the cell still has no on-screen area.
    """
    root, _ = _root(args.get("scope"))
    g = _grid(root, args.get("grid"))
    r = _row(g, args["row"])
    c = _col(g, args["column"])
    try:
        if not r.Displayed:
            g.FirstDisplayedScrollingRowIndex = r.Index  # scroll so the row is the first one shown
    except Exception:
        pass
    try:
        if not c.Displayed and not c.Frozen:
            g.FirstDisplayedScrollingColumnIndex = c.Index  # e.g. Layer Manager's Delete column in a narrow pane
    except Exception:
        pass
    # False = the whole cell rectangle, not only its visible part; it is empty when the cell is not on screen
    rect = g.GetCellDisplayRectangle(c.Index, r.Index, False)
    if rect.Width <= 0 or rect.Height <= 0:
        raise Exception("Cell is not visible on screen (pane too small or column scrolled away)")
    # image columns (icons such as the red X) carry no identifying text, so they are left out of row_values
    ident = dict((str(k.Name), _cell_text(r.Cells[k.Index].Value)) for k in g.Columns if k.Visible and not k.GetType().Name.endswith("ImageColumn"))
    return {"hwnd": int(g.Handle.ToInt64()), "x": rect.Left + rect.Width // 2, "y": rect.Top + rect.Height // 2,
            "row": r.Index, "row_values": ident, "column": str(c.Name)}


# ---------------------------------------------------------------------------
# Scope resolution: which part of TBC's UI a call works on
# ---------------------------------------------------------------------------
def _root(scope):
    """Resolve a scope string to (root control, command or None). Every action starts here.

    'pane:<title>'      the docked pane with that caption (case-insensitive exact match); raises if it is closed
                        (open it first, e.g. run_command layermanager) or unknown (the message lists the panes).
                        Returns (pane.Control, None).
    'dialog[:<i>]'      the i-th entry of _modal_forms() (default 0); raises if there is no such popup.
                        Returns (Form or WPF Window, None). Any scope starting with 'dialog' takes this branch.
    'command' / None    the open command's panel: (cmd.CommandUI, cmd). Raises when no command is open or the
                        command has no panel (some commands act immediately instead).
    Any other string also falls through to the command panel. Read-only.
    """
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
# A TBC panel is a tree of WinForms controls. What the user sees as ONE field is often a composite TBC control
# (namespace Trimble.Vce.UI.Controls...) wrapping an inner editor (a TextBox called 'ClientBox', a combo box ...).
# Discovery finds the inner editor (the "target", which holds the value), climbs to the composite (the "wrapper",
# which has the Name, Enabled/Visible state, status message and picker methods) and finds its caption label.
# ---------------------------------------------------------------------------
def _has_labels(c):
    """True when container c directly holds at least one Label: then c is a layout container (it carries the
    captions of several fields), not part of one composite field, and _wrapper stops climbing below it."""
    for k in c.Controls:
        if isinstance(k, Label):
            return True
    return False


def _wrapper(c):
    """Climb from an inner editor to the composite TBC control the user sees as one field.

    Climbs at most 3 parents, and only while the parent is a TBC control (class full name starting with
    'Trimble.Vce.UI.Controls'), is not a Form and holds no Label of its own. Plain WinForms containers (Panel,
    GroupBox ...) stop the climb, so a stock TextBox in a panel is its own wrapper. Returns the wrapper control.
    Read-only.
    """
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
    """Nearest label left of (or above) the field; looks one container further out if needed.

    w: the field's wrapper control. Returns the cleaned label text or None. First searches the Labels that are
    siblings of w; if none fits, searches the grandparent's Labels, with w's bounds translated into the grandparent's
    coordinates (control Bounds are relative to the direct parent, so the parent's Left/Top are added). This covers
    layouts where a field sits in its own small container next to the label. Read-only.
    Labels found this way can be wrong in some panels (Transform Survey Points, Linear Dimension: lessons 25, 68);
    that is why fields also carry an id.
    """
    r = _label_in(w.Parent, w.Bounds)
    if r is None and w.Parent is not None and w.Parent.Parent is not None and not isinstance(w.Parent, Form):
        pb = w.Parent.Bounds
        b = w.Bounds
        from System.Drawing import Rectangle
        r = _label_in(w.Parent.Parent, Rectangle(b.Left + pb.Left, b.Top + pb.Top, b.Width, b.Height))
    return r


def _label_in(p, wb):
    """Best caption Label among the direct children of container p for a field with bounds wb (p's coordinates).

    Geometry heuristic, in pixels:
      - "left" candidates: the label ends at most 6 px past the field's left edge and its vertical centre is within
        max(field height, 16) of the field's centre; score = horizontal gap + 3 x vertical offset (rows matter more
        than distance).
      - "above" candidates (only if not a left candidate): the label ends at most 6 px below the field's top and its
        left edge is within 60 px of the field's; score = vertical gap + left-edge offset.
    The best left candidate wins; otherwise the best label above; otherwise None.
    Invisible labels, empty labels and labels whose text is just '?' are ignored ('?' is what TBC coordinate boxes
    show when empty, per the command_ui_automation skill, so it is not a caption). Returns cleaned text. Read-only.
    """
    if p is None:
        return None
    wc = wb.Top + wb.Height / 2.0  # vertical centre of the field
    best, bd = None, 1e9   # best label to the left and its score
    above, ad = None, 1e9  # best label above and its score
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
    """WinForms visibility of c (Control.Visible is False when c OR any parent is hidden, e.g. a collapsed section).

    Anything without a readable Visible counts as visible. For WPF elements use _live instead.
    """
    try:
        return bool(c.Visible)
    except Exception:
        return True


class Field(object):
    """One input field found in a panel (WinForms or WPF). Plain data holder, built by _collect / _walk_wpf.

    kind     'text' | 'entity' | 'bool' | 'radio' | 'choice' | 'number' | 'list' | 'ultra' (see the module docstring)
    wrapper  the control the user sees as the field (TBC composite or the control itself): used for the id, the
             Enabled/Visible state, StatusMessage and picker methods (SetEntity, SerialNumber)
    target   the control that actually holds the value (inner text box, combo box ...); values are read from and
             written to it
    label    on-screen caption (or None)
    tech     'winforms' or 'wpf' (selects IsChecked/IsEnabled/IsVisible vs Checked/Enabled/Visible etc.)
    id       assigned afterwards by _collect (control name, de-duplicated with '#2', '#3' ...)
    """
    def __init__(self, kind, wrapper, target, label, tech="winforms"):
        """Store the attributes; the id is filled in later by _collect."""
        self.kind, self.wrapper, self.target, self.label, self.tech = kind, wrapper, target, label, tech
        self.id = None


def _collect(root, include_hidden=False):
    """Walk a panel / popup / pane and return (fields, buttons, texts).

    root: a WinForms control, or a WPF element (a WPF popup window) which is walked by _walk_wpf instead.
    include_hidden: also walk invisible controls (collapsed sections, inactive alternative groups); fill and
        editor_button always pass True so any field can be matched, state passes the caller's choice.
    Returns:
      fields  [Field] in tree order, each with a unique id (see the end of this function)
      buttons [button controls] (WinForms ButtonBase / Infragistics UltraButton, WPF ButtonBase)
      texts   [Label / TextBlock controls] with static text, for state's "texts" (WinForms: at most 150)
    Read-only: nothing is focused, clicked or changed.
    The checks below run in a fixed order and the first that matches claims the control (and usually its whole
    subtree), so the order matters: e.g. CheckBox and RadioButton derive from ButtonBase and must be tested
    before the button check.
    """
    fields, buttons, texts = [], [], []

    def add(kind, c, target, label=None):
        """Record a field. Without an explicit label the wrapper is found by climbing (_wrapper) and the label by
        geometry (_label_for); with a label (check boxes / radio buttons) c itself is the wrapper."""
        w = _wrapper(c) if label is None else c
        fields.append(Field(kind, w, target, label if label is not None else _label_for(w)))

    def walk(c):
        """Classify control c (see the order note above) and recurse into containers."""
        if not include_hidden and not _visible(c):
            return  # hidden control: skip it and its whole subtree
        tn = c.GetType().Name
        kids = list(c.Controls)
        # TBC composite entry controls keep their editor in a child named 'ClientBox' (the target). If the composite
        # can link an object (has SetEntity) it is an object picker ('entity'), otherwise a text entry. The field's
        # wrapper is found by climbing from the composite (_wrapper); its children are not walked.
        client = [k for k in kids if k.Name == "ClientBox"]
        if client:
            add("entity" if hasattr(c, "SetEntity") else "text", c, client[0])
            return
        if tn == "BrowseFile":  # TBC file chooser: a path box (+ Browse button); type the path into it
            # prefer the visible FilePathTextBox; some BrowseFile controls use a FilePathComboBox instead.
            # Typing the full path works for e.g. Write FXL to CSV's Target file (lesson 35).
            box = [k for k in kids if k.Name == "FilePathTextBox" and k.Visible] or [k for k in kids if k.Name == "FilePathComboBox"]
            if box:
                add("text", c, box[0])
                return
            # no path box found: fall through and walk the BrowseFile's children like any container
        if isinstance(c, CheckBox):
            # the check box's own text is its label; only a caption-less box looks for a nearby Label
            add("bool", c, c, _clean(c.Text) or _label_for(c))
            return
        if isinstance(c, RadioButton):
            add("radio", c, c, _clean(c.Text) or _label_for(c))
            return
        if isinstance(c, TextBoxBase):  # TextBox, RichTextBox, MaskedTextBox
            add("text", c, c)
            return
        if isinstance(c, ComboBox):
            add("choice", c, c)
            return
        if isinstance(c, NumericUpDown):
            add("number", c, c)
            return
        if isinstance(c, ListBox):  # also CheckedListBox (a ListBox subclass): _set ticks its items
            add("list", c, c)
            return
        # Infragistics editors (UltraTextEditor, UltraComboEditor, UltraCheckEditor ...): handled as kind 'ultra';
        # _value/_set tell them apart by their members (Items, Checked)
        if tn.startswith("Ultra") and ("Editor" in tn or tn == "UltraCheckEditor"):
            add("ultra", c, c)
            return
        if isinstance(c, ButtonBase) or tn in ("UltraButton", "UltraDropDownButton"):
            # keep buttons that have a caption, or whose Name ends in 'button'; buttons with neither are not listed
            if (c.Text or "").strip() or (c.Name and c.Name.lower().endswith("button")):
                buttons.append(c)  # icon-only buttons (e.g. Adjust Traverse's addButton) are pressed by id
            return
        if isinstance(c, Label):
            # static text (messages, captions, results); '?' placeholders are skipped as in _label_in
            t = (c.Text or "").strip()
            if t and t != "?" and len(texts) < 150:
                texts.append(c)
            return
        if tn == "ElementHost" and HAVE_WPF:
            # WinForms host for WPF content (macro panels, WPF pickers): continue in the WPF tree.
            # [None] is a fresh "last label seen" cell for this WPF subtree (see _walk_wpf).
            try:
                if c.Child is not None:
                    _walk_wpf(c.Child, fields, buttons, texts, include_hidden, [None])
            except Exception:
                pass
            return
        for k in kids:  # any other control is a container: look inside
            walk(k)

    if HAVE_WPF and isinstance(root, DependencyObject):
        _walk_wpf(root, fields, buttons, texts, include_hidden, [None])  # WPF window (popup)
    else:
        walk(root)
    # assign stable ids: control name, de-duplicated
    # The base id is the wrapper's Name, else the target's Name, else the label (or the kind) with spaces turned into
    # '_'. The 2nd, 3rd ... field with the same base gets '#2', '#3' ... in tree order. Ids are stable for an
    # unchanged panel, but they are recomputed on every call, so a panel that rebuilds itself can renumber them.
    # include_hidden changes the walk and can therefore shift the '#n' suffixes too.
    seen = {}
    for f in fields:
        base = _name_of(f.wrapper) or _name_of(f.target) or (f.label or f.kind).replace(" ", "_")
        n = seen.get(base, 0) + 1
        seen[base] = n
        f.id = base if n == 1 else "%s#%d" % (base, n)
    return fields, buttons, texts


def _name_of(c):
    """The control's Name (WinForms Control.Name or WPF FrameworkElement.Name) as str, or None if empty/missing."""
    try:
        n = c.Name
        return str(n) if n else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# WPF field discovery (macro panels, WPF popups, WPF parts of TBC panels)
# WPF has no geometry-based labels here: the caption of a box is the text seen just before it in the logical tree.
# ---------------------------------------------------------------------------
def _wpf_text(content, depth=0):
    """Text of a WPF Content value (string, TextBlock, AccessText, or a container holding one).

    Used for button captions, check box / radio captions and WPF Label contents. A ContentControl or Panel is
    searched (first child with text wins) at most 4 levels deep. Returns cleaned text or None. Read-only.
    Note: AccessText marks its access key with '_' (not '&'), and _clean does not strip '_'.
    """
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
    """Walk a WPF element's LOGICAL tree, appending to the caller's fields / buttons / texts lists.

    o: the element; include_hidden: also walk elements whose IsVisible is False; last_label: a one-item list used
    as a mutable cell shared by the whole recursion, holding the most recent caption text seen.
    Labelling rule: every TextBlock / Label with text becomes last_label; the next TextBox or ComboBox takes it as
    its label and clears it (so one caption labels one box). Check boxes and radio buttons use their own content
    first and do not clear last_label. Buttons are only listed when they have caption text (unlike WinForms, an
    icon-only WPF button is not listed). Elements are not given a wrapper: wrapper and target are the same element.
    The logical tree (what the XAML declares) is used, not the visual tree, so template parts (e.g. the TextBox
    inside a ComboBox's template) are not reported as separate fields. Non-DependencyObject children (plain strings
    in content) are skipped. Read-only.
    """
    if not isinstance(o, DependencyObject):
        return
    try:
        if not include_hidden and isinstance(o, FrameworkElement) and not o.IsVisible:
            return  # IsVisible is False when the element or any ancestor is collapsed/hidden
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
    # checked after CheckBox / RadioButton, which are ButtonBase subclasses too
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
# Reading: _value / _options / _enabled / _status / _describe turn a Field into the JSON shape state reports.
# Writing: _set (with _commit and the helpers after it) enters one value the way a user would.
# ---------------------------------------------------------------------------
def _item_text(t, x):
    """The text the user sees for a list item: WinForms GetItemText honours DisplayMember / Format, so items that
    are .NET objects (Scale Bar type, Sheet set type, Leader type ...) show their caption, not a type name.

    t: the list control (ComboBox / ListBox / CheckedListBox, or a WPF ComboBox which has no GetItemText);
    x: one item. Order: GetItemText (a result starting with '<' is not accepted; the code does not record why),
    then the first non-callable DisplayText / DisplayName / Name / Caption attribute, then str(x). Lesson 80.
    """
    try:
        if hasattr(t, "GetItemText"):
            s = str(t.GetItemText(x))
            if s and not s.startswith("<"):
                return s
    except Exception:
        pass
    # fallback: common caption properties of item objects (callable = a method, not a property value)
    for attr in ("DisplayText", "DisplayName", "Name", "Caption"):
        try:
            v = getattr(x, attr, None)
            if v is not None and not callable(v):
                return str(v)
        except Exception:
            pass
    return str(x)


def _options(f):
    """The options shown to the caller for a drop-down / list field (first MAX_OPTIONS only), else None.

    choice / list: on-screen item texts (_item_text). ultra with Items (Infragistics combo editors): each item's
    DisplayText. Anything unreadable gives None rather than an error. Read-only.
    """
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
    """Current value of a field as TBC shows it (JSON-friendly). Read-only.

    bool / radio -> True/False; number -> float; entity (object picker) -> {"serial": n, "text": shown text}, or ''
    when nothing is linked (SerialNumber 0); list -> [ticked item texts] for a checkbox list, else [selected items
    as str()]; Infragistics check editor -> bool; WPF combo box -> str(SelectedItem) or its Text; everything else ->
    the target's Text ('' for None). Never raises: an unreadable control gives the string '<unreadable: ...>', so
    one odd control cannot break a whole state / fill reply.
    """
    t = f.target
    try:
        if f.kind in ("bool", "radio"):
            return bool(t.IsChecked) if f.tech == "wpf" else bool(t.Checked)
        if f.kind == "number":
            return float(t.Value)  # NumericUpDown.Value is a .NET Decimal
        if f.kind == "entity":
            # the picker composite (wrapper) knows the linked object's serial; 0 = nothing linked
            s = int(f.wrapper.SerialNumber)
            return {"serial": s, "text": str(f.wrapper.Text or "").strip()} if s else ""
        if f.kind == "list":
            if hasattr(t, "CheckedItems"):  # checkbox list: the ticked items are its value
                return [_item_text(t, x) for x in t.CheckedItems]
            # note: plain list boxes report str(item), not _item_text, so object items may show a type name here
            return [str(x) for x in t.SelectedItems]
        # an Infragistics editor with Checked but no Items is an UltraCheckEditor
        if f.kind == "ultra" and hasattr(t, "Checked") and not hasattr(t, "Items"):
            return bool(t.Checked)
        if f.kind == "choice" and f.tech == "wpf":
            return str(t.SelectedItem) if t.SelectedItem is not None else (t.Text or "")
        return str(t.Text) if t.Text is not None else ""
    except Exception as ex:
        return "<unreadable: %s>" % ex


def _enabled(f):
    """Whether the field's wrapper is enabled (WPF IsEnabled / WinForms Enabled); True if unreadable.
    _set refuses to write into a disabled field."""
    try:
        return bool(f.wrapper.IsEnabled) if f.tech == "wpf" else bool(f.wrapper.Enabled)
    except Exception:
        return True


def _status(f):
    """TBC's status/validation message for a field, or None.

    TBC entry controls expose a StatusMessage property (wrapper first, then target), e.g. when a typed value was
    rejected. state reports it as the field's "status", and the server's ui_after turns it into "field_status"
    (how a rejected value shows up after pressing a button). Read-only.
    """
    for c in (f.wrapper, f.target):
        try:
            s = c.StatusMessage
            if s:
                return str(s)
        except Exception:
            pass
    return None


def _describe(f):
    """A field as reported by state: {id, label, kind, value} plus optional keys only when they carry information.

    enabled=False when disabled; visible=False when a WinForms field is hidden (only seen with include_hidden);
    options when the field has any; status when TBC shows a message; control = the wrapper's class name whenever it
    is not a stock TextBox/ComboBox/CheckBox/RadioButton (e.g. 'SelectPlanar1', 'ElevationEdit', 'CoordinateEdit'),
    which tells the caller which special handling _set will apply. Read-only.
    """
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


# ---------------------------------------------------------------------------
# Buttons (description) and field matching
# ---------------------------------------------------------------------------
def _btn_text(b):
    """Cleaned caption of a WinForms or WPF button, or None (icon-only buttons)."""
    if HAVE_WPF and isinstance(b, DependencyObject):
        return _wpf_text(b.Content)
    try:
        return _clean(b.Text)
    except Exception:
        return None


def _btn_desc(b):
    """A button as reported by state: {"id": Name or caption, "text": caption, "enabled": False only if disabled}.

    Icon-only buttons have text None and are addressed by their id (e.g. Adjust Traverse's 'addButton'). The
    server's dialogs_snapshot lists popup buttons by text, else id.
    """
    d = {"id": _name_of(b) or _btn_text(b), "text": _btn_text(b)}
    try:
        en = b.IsEnabled if HAVE_WPF and isinstance(b, DependencyObject) else b.Enabled
        if not en:
            d["enabled"] = False
    except Exception:
        pass
    return d


def _live(f):
    """Whether the user can currently see the field (WPF IsVisible / WinForms Visible of the wrapper).

    Used by _match to pick the active one among same-named fields. True if unreadable.
    """
    try:
        return bool(f.wrapper.IsVisible) if f.tech == "wpf" else bool(f.wrapper.Visible)
    except Exception:
        return True


def _match(fields, key):
    """Find the field a caller means by `key` (an id or an on-screen label), case-insensitively. Read-only.

    Order of preference:
      1. id: fields whose id equals key, or whose id without its '#n' suffix equals key (so 'coordinateEdit' also
         finds 'coordinateEdit#3'). Among those: the only visible one; else the exact id if it is visible (or none
         are visible); else the first visible one.
      2. exact label: a single hit wins; if several fields share the label, the only visible one wins; otherwise
         (none or several of them visible) it raises "ambiguous" with the candidate ids.
      3. label prefix: a key that starts exactly one label (e.g. 'North' for 'Northing').
    Raises with the list of "id (label)" when nothing matches (also when several labels share the prefix).
    Lesson 29: panels with alternative input groups reuse control names; the visible one is the active group.
    """
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
    """Tab out of the field so TBC parses/validates it like a user entry.

    root: the panel root (for SelectNextControl); f: the field just written.
    WPF: push the TextBox's Text binding to its source now (bindings often update only on focus loss), then move
    keyboard focus to the next element, exactly what Tab does.
    WinForms: call ValidateInput(True) on the first of wrapper / target that has it (TBC composite controls expose
    their own validation), then move focus to the next control in tab order.
    Side effects: keyboard focus moves away from the field; TBC's parse/validate handlers run (they may reformat
    the value, e.g. 10500 -> 10500.000, or reset it). Errors are swallowed: a field that cannot be tabbed out of
    is still reported by the caller's re-read.
    """
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
                f.target.Focus()  # focus must be in the box for "move to next" to start from it
            f.target.MoveFocus(TraversalRequest(FocusNavigationDirection.Next))  # = Tab
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
        # SelectNextControl(start, forward, tabStopOnly, nested, wrap): focus the next tab stop after the field,
        # searching nested containers and wrapping around, i.e. the Tab key
        root.SelectNextControl(f.target, True, True, True, True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# _set: enter one value into one field
# ---------------------------------------------------------------------------
def _set(root, f, v):
    """Enter value v into field f the way a user would. Returns nothing; fill re-reads the value afterwards.

    root: panel root (for _commit); f: a Field from _collect; v: the caller's value (str, number, bool, list, or a
    dict such as {"serial": n}, {"only": [...]} or {"type": "..."}).
    Raises: field disabled; radio set to False (WinForms); value not among a drop-down's options; list items
    missing; serial not in the project.
    The branches run top to bottom and the first that applies returns. Summary:
      bool / radio      truthy words '1', 'true', 'yes', 'on', 'checked'. WPF: IsChecked. WinForms radio:
                        PerformClick. WinForms check box: a real mouse click on the glyph, if the state differs.
      number            NumericUpDown.Value, then tab out.
      entity            int or {"serial": n}: link that object (SetEntity); anything else is typed as text below.
      numeric text box  a writable Double `Value` property: set it, then tab out (typed Text is ignored there).
      ultra             check editor: Checked; text editor: Text + tab out; combo editor: as choice.
      checkbox list     tick the named items; {"only": [...]} also unticks all others.
      choice / list     select the option whose text equals v (else the only option containing v), tab out.
                        Editable WinForms combo boxes accept other text; drop-down lists raise.
      text              {"type": s}: keystrokes appended (no Enter, no tab-out); multi-line str: keystrokes;
                        WPF picker + int/{"serial"}: SetEntity; MemberSelection + list of serials: SetSelection;
                        LeftRightEdit: Side enum; CoordinateEdit: keystrokes + Enter; WPF "value" ending in a
                        newline: Text + one Enter; otherwise focus, set Text, tab out.
    Side effects: focus changes, clicks, keystrokes and whatever TBC does in response (previews, recompute of the
    panel, auto-advance). `prj` (the open project) comes from the bridge's namespace.
    """
    t = f.target
    if not _enabled(f):
        raise Exception("Field '%s' is disabled" % f.id)
    # --- check boxes and radio buttons ---
    if f.kind in ("bool", "radio"):
        b = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on", "checked")
        if f.tech == "wpf":
            # WPF: set IsChecked directly (no click). Note: unlike WinForms, this also lets a radio be set to False.
            t.IsChecked = b
            return
        # Click like a user so the panel's own Click/CheckedChanged handlers run (setting .Checked in code
        # can leave the command's internal mode out of sync, e.g. Change Elevation applied 'undefined').
        if f.kind == "radio":
            if not b:
                raise Exception("Can't un-select a radio option directly; select another option instead")
            t.PerformClick()  # raises the radio's Click as a user click would
            if not t.Checked:
                t.Checked = True  # fallback when PerformClick did not check it
            return
        if bool(t.Checked) != b:
            # synchronous in-process click 8 px from the left, vertically centred
            _mouse_click(t, 8, t.Height // 2)  # the check box glyph sits at the left edge
            if bool(t.Checked) != b:
                t.Checked = b  # fallback when the click did not toggle it
        return
    # --- NumericUpDown: its Value is a .NET Decimal ---
    if f.kind == "number":
        t.Value = Decimal(float(v))
        _commit(root, f)
        return
    # --- object pickers: link by serial only for real numbers (see _resolve_serial), else fall through to typing ---
    if f.kind == "entity":
        serial = _resolve_serial(v)  # raises for a non-existent serial; None for text
        if serial is not None:
            f.wrapper.SetEntity(UInt32(serial), prj)
            return
        # text (e.g. a point ID or a new name): type it like the user would and let TBC parse it
        # (SetEntity(serial, project) is the picker's own "link this object" method; `prj` is the open project)
    # --- TBC numeric boxes: typed Text is ignored, the Double Value must be set (see _is_numeric_edit) ---
    if f.kind == "text" and _is_numeric_edit(t):
        try:
            t.Value = float(v)
            _commit(root, f)
            return
        except (TypeError, ValueError):
            pass  # float() could not parse v (or v is a dict/None): fall through and type it as text
    # --- Infragistics editors without a list ---
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
    # --- checkbox lists (CheckedListBox or anything with SetItemChecked) ---
    # (operator precedence: "A and B or (C and D)" = (A and B) or (C and D), i.e. a list field that is either kind)
    if f.kind == "list" and t.GetType().Name == "CheckedListBox" or (f.kind == "list" and hasattr(t, "SetItemChecked")):
        # checkbox list (Select by Layer, quality/type filters): tick the named items like the user, untick the rest
        # only when given {"only": [...]}; a plain string or list ticks those items and leaves others as they are
        items = list(t.Items)
        texts = [_item_text(t, x) for x in items]
        only = isinstance(v, dict) and "only" in v
        want = v["only"] if only else (v if isinstance(v, (list, tuple)) else [v])
        want_l = [str(w).strip().lower() for w in want]
        # all requested items must exist before anything is ticked, so a typo changes nothing
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
    # --- drop-downs and single-select lists: pick an existing option by its on-screen text ---
    if f.kind in ("choice", "ultra", "list"):
        items = list(t.Items) if hasattr(t, "Items") else []
        # Infragistics value-list items show DisplayText; WinForms/WPF items use _item_text
        texts = [str(x.DisplayText) if f.kind == "ultra" and hasattr(x, "DisplayText") else _item_text(t, x) for x in items]
        want = str(v).strip().lower()
        # 1) exact text (trimmed, case-insensitive)
        idx = next((i for i, s in enumerate(texts) if s.strip().lower() == want), None)
        if idx is None:
            # 2) otherwise a substring, but only if exactly one option contains it
            c = [i for i, s in enumerate(texts) if want in s.lower()]
            idx = c[0] if len(c) == 1 else None
        if idx is not None:
            # the three branches below are identical (SelectedIndex works for every kind handled here)
            if f.kind == "ultra":
                t.SelectedIndex = idx
            elif f.kind == "list":
                t.SelectedIndex = idx
            else:
                t.SelectedIndex = idx
            _commit(root, f)
            return
        # no option matched: an editable WinForms combo box (DropDownStyle Simple/DropDown) accepts free text, like
        # a user typing into it; a DropDownList (and every other list) only accepts its options
        if f.kind == "choice" and f.tech == "winforms" and str(t.DropDownStyle) != "DropDownList":
            t.Focus()
            t.Text = str(v)
            _commit(root, f)
            return
        raise Exception("'%s' is not an option for '%s'. Options: %s" % (v, f.id, texts[:MAX_OPTIONS]))
    # --- text entry (kind 'text', and 'entity' given a string) ---
    # The special cases are tried first; the plain "focus, set Text, tab out" path is at the very end.
    if f.tech == "winforms" and isinstance(v, dict) and "type" in v and isinstance(t, TextBoxBase):
        _type_keys(t, str(v["type"]))  # {"type": "..."}: keystrokes appended at the end, no Enter, no tab-out
        return
    if f.tech == "winforms" and isinstance(v, str) and "\n" in v and isinstance(t, TextBoxBase):
        _type_keys(t, v)  # multi-line command text: type it line by line like the user
        return
    # WPF: an int (bool excluded, since bool is an int subclass) or {"serial": n} given to a box inside a WPF
    # SelectEntity picker (lesson 62); WPF boxes are found as kind 'text', so the entity branch above did not apply
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
        # (lesson 60). SetSelection takes a .NET List<UInt32>; every serial is checked first (_resolve_serial raises
        # for one that does not exist), so a bad serial is never linked. A partly built list is simply discarded.
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
        # (lesson 55). 'left' / 'LEFT' -> 'Left'; parsed against the Side property's own enum type, so a value that
        # is not one of its names raises
        import System
        lr.Side = System.Enum.Parse(lr.Side.GetType(), str(v).strip().capitalize())
        return
    ce = _coordinate_edit(t, f)
    if ce is not None and v is not None and str(v).strip():
        # TBC CoordinateEdit (Point one/Corner/Start point ...): setting Text or SetCoordinate in code shows the value
        # but some commands (Three-Point Circle/Rectangle) still say "Pick a point in a Plan View". Real keystrokes
        # plus Enter go through TBC's keyboard input path and work everywhere (point ID or "N,E[,Z]").
        # (lesson 51). Select the old content so the typed text replaces it; any newlines in v are dropped and
        # exactly one Enter is pressed at the end. A WPF CoordinateEdit has no WinForms inner box (_inner_textbox
        # returns None) and falls through to the plain Text path below, which works there.
        tb = _inner_textbox(ce)
        if tb is not None:
            tb.Focus()
            tb.SelectAll()
            _type_keys(tb, str(v).replace("\n", "") + "\n")
            return
    if f.tech == "wpf" and isinstance(v, str) and v.endswith("\n"):
        # "value\n": type it and press Enter without leaving the box (Quick Line / Outline add one vertex per Enter)
        # (lesson 60: don't use this where Enter means OK; Capture Outline treats Enter as finish, lesson 53)
        t.Focus()
        t.Text = v.rstrip("\n")
        _wpf_enter(t)
        return
    # default: the user's way of entering a value - click into the box, type, Tab out
    try:
        t.Focus()  # WinForms and WPF: enter the box like the user before typing
    except Exception:
        pass
    t.Text = "" if v is None else str(v)
    _commit(root, f)


def _wpf_enter(t):
    """Press Enter once in a WPF element. Only the Preview events are sent: the input manager promotes them to
    KeyDown/KeyUp itself, so sending those too would be a second Enter (which hit the default OK button).

    t: the WPF element that should receive the key (it should have keyboard focus; _set focuses it first).
    The events are pushed through InputManager.ProcessInput, i.e. WPF's real input pipeline, so the element's key
    handlers run as for a physical key press. Synchronous. Used for "value + newline" in WPF boxes (Quick Line adds
    one vertex per Enter, lesson 60).
    """
    from System.Windows.Input import Keyboard, Key, KeyEventArgs, InputManager
    from System.Windows import PresentationSource
    src = PresentationSource.FromVisual(t)  # the window/host the key event is reported as coming from
    for ev in (Keyboard.PreviewKeyDownEvent, Keyboard.PreviewKeyUpEvent):
        # KeyEventArgs(device, source, timestamp 0, key); RoutedEvent picks key-down vs key-up
        e = KeyEventArgs(Keyboard.PrimaryDevice, src, 0, Key.Enter)
        e.RoutedEvent = ev
        InputManager.Current.ProcessInput(e)


# ---------------------------------------------------------------------------
# Helpers for _set: locating TBC's special controls behind a field, and serial checks
# ---------------------------------------------------------------------------
def _inner_textbox(c):
    """First WinForms TextBoxBase in c's subtree (c itself included, depth-first), else None.

    Returns None for WPF elements (anything that is not a WinForms Control), see the comment below. Read-only.
    """
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
    """The Trimble CoordinateEdit behind a field (the control itself, its wrapper or a parent), else None.

    CoordinateEdit is TBC's point/coordinate entry box (Point one, Corner, Start point ...): it takes a point ID or
    'N,E[,Z]' and needs real keystrokes + Enter on WinForms (lesson 51).
    """
    return _typed_parent(t, f, "CoordinateEdit")


def _wpf_ancestor(t, type_name, depth=8):
    """Nearest WPF visual ancestor (or the element itself) whose class name is `type_name`, else None.

    Walks up the VISUAL tree (VisualTreeHelper.GetParent) at most `depth` levels, comparing the short class name
    (e.g. 'SelectEntity', i.e. Trimble.Vce.UI.Controls.Wpf.SelectEntity, lesson 62). Any error gives None.
    Read-only.
    """
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
    """The control of class `type_name` behind a field (the control itself, its wrapper or a parent), else None.

    Candidates, in order: the field's wrapper, the target t, t's parent and grandparent (Parent works for WinForms
    controls and WPF FrameworkElements alike). Compared by short class name, e.g. 'CoordinateEdit',
    'MemberSelection', 'LeftRightEdit', so no reference to TBC's UI assemblies is needed. Read-only.
    """
    cands = [getattr(f, "wrapper", None), t]
    try:
        cands += [t.Parent, t.Parent.Parent]
    except Exception:
        pass  # no parent (or no grandparent): check what we have
    for c in cands:
        try:
            if c is not None and c.GetType().Name == type_name:
                return c
        except Exception:
            pass
    return None


def _is_numeric_edit(t):
    """TBC NumericEdit-style boxes ignore typed Text; their Double `Value` must be set.

    True when t's class has a public, writable property named Value of type Double (found by .NET reflection).
    Any error gives False. Read-only.
    """
    try:
        p = t.GetType().GetProperty("Value")
        return p is not None and p.CanWrite and p.PropertyType.Name == "Double"
    except Exception:
        return False


def _resolve_serial(v):
    """Serial number for a picker field, ONLY when the caller passed a real number ({"serial": n} or an int).
    Strings are never treated as serials: '4700486' is a point ID typed by the user, not object #4700486.
    (Treating it as a serial linked TBC to a non-existent object and crashed it during Compute, 2026-10-13.)
    The serial must exist, otherwise refuse.

    Returns the serial as int, or None when v is not a number (bool is excluded explicitly because bool is an int
    subclass in Python). Raises "No object with serial ..." when the number is 0, negative or not in the project.
    prj.Concordance is the project's serial-number -> object lookup; `prj` comes from the bridge's namespace.
    Read-only.
    """
    if isinstance(v, dict):
        v = v.get("serial")
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    # 0 and negatives are refused without a lookup (UInt32 cannot hold a negative)
    o = prj.Concordance.Lookup(UInt32(v)) if v > 0 else None
    if o is None:
        raise Exception("No object with serial %s in the project" % v)
    return int(v)


# ---------------------------------------------------------------------------
# Buttons: finding and pressing
# ---------------------------------------------------------------------------
def _find_button(buttons, key):
    """The button meant by key: first by control Name (exact, case-insensitive), else by caption.

    If several buttons share the caption, the LAST one in tree order is taken (see the comment below). Raises with
    the list of buttons when nothing matches. Note: _clean(key) returns None for an empty key, which then fails
    with an AttributeError rather than a friendly message. Read-only.
    """
    k = _clean(key).lower()
    for b in buttons:
        if (_name_of(b) or "").lower() == k:
            return b
    hits = [b for b in buttons if (_btn_text(b) or "").lower() == k]
    if hits:
        return hits[-1]  # the command's own buttons come after the frame's
    raise Exception("No button '%s'. Buttons: %s" % (key, [_btn_desc(b) for b in buttons]))


def _press(b):
    """Press asynchronously so a modal popup can't block the bridge.

    b: a WinForms button (PerformClick) or a WPF button (UI Automation Invoke pattern through
    ButtonAutomationPeer, the WPF way of clicking a button from code: it raises Click and runs its Command).
    The press is QUEUED with MainForm.BeginInvoke and runs on the UI thread after this bridge call has returned.
    If it ran inline and opened a modal popup (e.g. a confirmation), the popup's message loop would keep this call,
    and therefore the bridge, waiting until someone closed it. Errors inside the press are swallowed; the server
    finds out what happened afterwards (ui_after: open command, popups, field status). Returns nothing.
    """
    def go():
        """Queued on the UI thread: press the button."""
        try:
            if HAVE_WPF and isinstance(b, DependencyObject):
                ButtonAutomationPeer(b).GetPattern(PatternInterface.Invoke).Invoke()
            else:
                b.PerformClick()
        except Exception:
            pass
    TrimbleOffice.TheOffice.MainForm.BeginInvoke(Action(go))


# ---------------------------------------------------------------------------
# actions (the functions named in the dispatch table at the end of the file)
# ---------------------------------------------------------------------------
def state(args):
    """ACTION state: describe what is open in TBC and the fields/buttons of one scope. Read-only.

    ARGS: scope ('command' default, 'dialog[:i]', 'pane:<title>'), include_hidden (also report fields in hidden or
    collapsed parts), include_text (default True: static texts such as messages).
    Always returns modal_dialogs (index, title, .NET type of every popup), open_command (key or None) and panes
    (title, open). With scope 'command' and no open command it stops there. Otherwise it adds:
      command {key, caption} (command scope) | pane {title, control} + grids (pane scope) | dialog {title},
      fields (see _describe), buttons (see _btn_desc), tabs (if the root has tab controls), texts (max 80, without
      texts that are also a field's label).
    Called by the server's ui_state, which most tools use (command_ui_open/inspect, dialogs_snapshot, ui_after,
    tbc_busy). A popup's message is read from its texts / text fields by the server.
    """
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
                # WPF texts are TextBlocks (Text) or Labels (Content); WinForms texts are Labels (Text)
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
    """ACTION fill: enter several values in order, optionally press a button. The heart of command_ui_fill and
    tbc_dialogs action=fill.

    ARGS: scope, values ([[label_or_id, value], ...] in the order a user would fill them, or a dict), press (button
    text or id, pressed only when every value went in), stop_on_error (default True: stop at the first failure).
    Flow per value: match the field (_match, over ALL fields including hidden ones, preferring visible), enter the
    value (_set), record what TBC now shows. After a radio / check box / drop-down / Infragistics editor / picker
    change the panel is re-read, because such options can rebuild parts of the panel (lesson 29).
    After all values: every field that was set is re-read once more (a later entry can make TBC reset an earlier
    one) and a "warning" is added when a requested non-empty value left the field empty.
    Returns {"set": [{field (id), label, requested, now, status}], "errors": [{field (as given), error}],
    "pressed": button text (if pressed)}.
    The press is asynchronous (_press): its effects (popups, recompute) are inspected by the server afterwards
    (ui_after), together with a short settle time and the wait for Compute Project. The server also applies its
    field-order guards (guard_fill) before calling this.
    """
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
            # matched again by id: if the panel rebuilt itself the id may now point at the new control
            f = _match(fields, d["field"])
            d["now"] = _value(f)
            d["status"] = _status(f)
            if str(d["now"]).strip() == "" and str(d["requested"]).strip() != "":
                d["warning"] = "field is empty after filling; TBC may have rejected or reset it"
        except Exception:
            pass  # the field is gone (panel rebuilt): keep the value recorded right after setting it
    out = {"set": done, "errors": errors}
    # never press after a failed entry: the panel would act on a half-filled form
    if args.get("press") and not errors:
        b = _find_button(buttons, args["press"])
        _press(b)
        out["pressed"] = _btn_text(b)
    return out


# ---------------------------------------------------------------------------
# Tabs inside panels (WinForms TabControl and Infragistics UltraTabControl)
# ---------------------------------------------------------------------------
def _tab_controls(root):
    """Every TabControl / UltraTabControl under a WinForms root, in tree order (hidden ones included; the walk
    continues inside them, so nested tab controls are found too). WPF roots return []. Matched by exact class
    name, so other tab-like controls (e.g. an UltraTabStrip, which lesson 81 mentions for Export) are not
    included. Read-only."""
    out = []

    def walk(c):
        """Depth-first search of c.Controls, collecting tab controls into `out`."""
        tn = c.GetType().Name
        if tn in ("UltraTabControl", "TabControl"):
            out.append(c)
        for k in c.Controls:
            walk(k)
    if not (HAVE_WPF and isinstance(root, DependencyObject)):
        walk(root)
    return out


def _tabs(root):
    """For state: [{"tabs": [tab captions], "selected": caption of the selected tab or None}] per tab control.

    UltraTabControl lists its tabs in .Tabs, a WinForms TabControl in .TabPages; both have SelectedTab.
    """
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
    """Select the first tab (in any tab control under root) whose caption equals name, case-insensitively.

    Sets SelectedTab directly (no mouse click), synchronously; the panel then shows that tab's page.
    Returns the tab's caption, or None when no tab has that name.
    """
    k = _clean(name).lower()
    for tc in _tab_controls(root):
        tabs = list(tc.Tabs) if tc.GetType().Name == "UltraTabControl" else list(tc.TabPages)
        for t in tabs:
            if (_clean(t.Text) or "").lower() == k:
                tc.SelectedTab = t
                return _clean(t.Text)
    return None


# ---------------------------------------------------------------------------
# Remaining actions: click, close, license, close_dialog, forms, close_forms, editor_button
# ---------------------------------------------------------------------------
def click(args):
    """ACTION click: press a button in a panel, popup or pane (command_ui_click, tbc_dialogs action=click, and the
    server's safe_dismiss for Cancel/Close/No).

    ARGS: scope, button (Name or caption). Only VISIBLE buttons are considered (_collect with include_hidden False).
    If no button matches, a tab with that caption is selected instead ("clicking a tab header").
    Returns {"pressed": caption} (the press itself is queued, see _press) or {"selected_tab": caption}.
    Which buttons may be pressed on a popup (license popups, safe buttons) is decided by the server, not here.
    """
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
    """ACTION close: close the open command panel (command_ui_close), or every open command with all=true.

    Uses TBC's own CommandHost.CloseCommand / CloseAll, synchronously (not queued). Returns {"closed": key of the
    command that was on top, or None when no command was open}.
    """
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
    """Silently check whether commands are licensed (no TBC license popup). keys -> {licensed, needs}.

    ACTION license. ARGS: keys (command keys as used by run_command). For each key, in the caller's spelling:
      {"exists": False}                                       not in TBC's command list
      {"exists": True, "licensed": True|False|None, "needs_any_of": [feature codes]}
    A command without license codes counts as licensed. "licensed" is None when TBC's check itself failed.
    How: the command's LicenseCodes (TBC license Features) are passed to Server.TheServer.CanUseFeature, which
    answers without showing anything, whereas running an unlicensed command would open TBC's license popup.
    Used by the server before every run_command / command_ui_open (check_license) and to mark list_commands
    entries. Read-only.
    """
    from System import Array
    from Trimble.Vce.Core import Server
    from Trimble.Vce.License import Feature
    srv = Server.TheServer
    cl = TrimbleOffice.TheOffice.CommandProcessor.CommandList
    out = {}
    for k in args.get("keys") or []:
        kk = str(k).lower()  # looked up lower-cased in TBC's command list
        if not cl.ContainsKey(kk):
            out[k] = {"exists": False}
            continue
        try:
            codes = list(cl[kk].LicenseCodes or [])
        except Exception:
            codes = []  # no readable license codes: treated as "needs nothing"
        try:
            # CanUseFeature gets the whole array of the command's features (Array[Feature] = Feature[] in .NET)
            ok = True if not codes else bool(srv.CanUseFeature(Array[Feature](codes)))
        except Exception as ex:
            ok = None
        out[k] = {"exists": True, "licensed": ok, "needs_any_of": [str(c) for c in codes]}
    return out


def close_dialog(args):
    """Close a TBC modal dialog the way the title-bar X does (no button is pressed).

    ACTION close_dialog. ARGS: index (position in _modal_forms(), default 0; WinForms popups first, then WPF).
    Calls the window's Close() (Form.Close / WPF Window.Close), queued with BeginInvoke so that whatever runs on
    closing cannot block the bridge. Returns {"closed": title} or {"closed": None} when there is no such popup.
    Used by the server's safe_dismiss when a popup has no Cancel/Close/No/Abort button, and always for license
    popups (only the user should change licensing).
    """
    forms = _modal_forms()
    i = int(args.get("index", 0))
    if i >= len(forms):
        return {"closed": None}
    f = forms[i]
    title = _title(f)
    TrimbleOffice.TheOffice.MainForm.BeginInvoke(Action(f.Close))  # queued; runs after this call returns
    return {"closed": title}


def forms(args):
    """Open top-level/MDI windows other than the main window: [{id, title, type, mdi}] (id = handle).

    ACTION forms. No ARGS. Each entry also has "modal". Only visible WinForms forms are listed (no WPF windows).
    id is the window handle as an int, valid until the window closes. The test suites (tests/tbc_testkit.py,
    tests/tab_survey.py ...) take a snapshot before a test and close the non-modal windows that appeared since
    (e.g. survey spreadsheet views, lesson 38) with close_forms. No MCP tool calls it. Read-only.
    """
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
    """Close the given (non-modal) windows by handle id, like their X button.

    ACTION close_forms. ARGS: ids (handles from `forms`). Never closes TBC's main window or a modal popup (popups
    go through close_dialog / the server's safe_dismiss). Each Close() is queued with BeginInvoke. Returns
    {"closed": [titles of the windows queued for closing]}. Used by the test suites, not by an MCP tool.
    """
    ids = set(int(i) for i in args.get("ids") or [])
    closed = []
    for f in list(Application.OpenForms):  # copy: the collection changes as forms close
        try:
            if int(f.Handle.ToInt64()) in ids and f is not TrimbleOffice.TheOffice.MainForm and not f.Modal:
                closed.append(str(f.Text))
                TrimbleOffice.TheOffice.MainForm.BeginInvoke(Action(f.Close))
        except Exception:
            pass
    return {"closed": closed}


def editor_button(args):
    """Click an Infragistics editor's built-in button (e.g. the '...' Browse button of a Source file box) with a
    genuine in-process mouse click, asynchronously (it usually opens a modal file dialog).

    ACTION editor_button. ARGS: scope, field (label or id, _match over all fields), index (default 0) into the
    editor's buttons, right-side buttons first, then left-side ones.
    The click point is the centre of the button's on-screen element (Infragistics UIElement rectangle, in the
    editor's client coordinates); if that cannot be found, 8 px from the editor's right edge, vertically centred.
    Returns {"clicked_editor_button": the button's Key, "field": id}. The click is queued with BeginInvoke.
    Status: lesson 36 records that the automated Browse click on Convert CSV to FXL's Source file did NOT open the
    file dialog (unresolved on 2026.10). No MCP tool calls this action.
    Note: ed is the field's wrapper; for an Infragistics editor nested inside a TBC composite control the wrapper is
    the composite (see _wrapper), which may not have ButtonsRight/ButtonsLeft.
    """
    root, _ = _root(args.get("scope"))
    fields, _, _ = _collect(root, True)
    f = _match(fields, args["field"])
    ed = f.wrapper
    # Infragistics editors keep their built-in buttons ('...', drop-down, spin) in ButtonsRight / ButtonsLeft
    btns = list(ed.ButtonsRight) + list(ed.ButtonsLeft)
    if not btns:
        raise Exception("Field '%s' has no editor buttons" % f.id)
    b = btns[int(args.get("index", 0))]
    el = None
    try:
        el = b.GetUIElement(ed.UIElement)  # the drawn element of that button inside the editor
    except Exception:
        el = None
    if el is not None:
        rc = el.Rect
        x, y = rc.X + rc.Width // 2, rc.Y + rc.Height // 2
    else:
        x, y = ed.Width - 8, ed.Height // 2  # editor buttons sit at the right edge
    TrimbleOffice.TheOffice.MainForm.BeginInvoke(Action(lambda: _mouse_click(ed, x, y)))
    return {"clicked_editor_button": str(b.Key), "field": f.id}


# ---------------------------------------------------------------------------
# Dispatch: the server prepended ACTION and ARGS; run the named action and hand its return value to the bridge
# through `result` (an unknown ACTION raises KeyError, reported back as an error).
# ---------------------------------------------------------------------------
result = {"forms": forms, "close_forms": close_forms, "editor_button": editor_button,
          "state": state, "fill": fill, "click": click, "close": close, "license": license,
          "close_dialog": close_dialog, "grid_read": grid_read, "grid_set": grid_set,
          "grid_cell_point": grid_cell_point, "grid_click": grid_click}[ACTION](ARGS)

