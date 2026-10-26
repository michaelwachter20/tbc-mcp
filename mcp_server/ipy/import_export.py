# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# IronPython 3.4 code executed INSIDE TBC by the MCP server. Prepended: ACTION, ARGS. Sets `result`.
# Drives the Home tab's Import pane (WPF, ImportCommand view model) and Export pane (WinForms) the way the panes
# themselves do: folder + file selection through the pane's own view model / grid adapter, format tabs and lists
# through their controls. Pressing Import / Export is left to command_ui (so popups are handled the usual way).
"""Import / Export pane helper run inside TBC through the bridge's execute_python.

How it is called
----------------
The server's run_ipy("import_export", ACTION, ARGS) reads this file fresh on every call, prepends `ACTION` and
`ARGS`, and runs it through the bridge's execute_python (transaction=False). It runs in the bridge's namespace, so
TrimbleOffice is used without importing it. The last line dispatches ACTION and stores the return value in
`result`. The pane must already be open: the server opens it first (t_command_ui_open with key "import" or
"export"), calls these actions, presses the button through command_ui and then closes the pane (t_import leaves
it open when an import failed and a TBC error dialog is still showing).

Callers: t_import() and t_export() in mcp_server/tbc_mcp_server.py (tools tbc_import / tbc_export). See the
home_import_export skill for the verified workflow and its pitfalls.

Import actions (Import pane open; WPF, driven through ImportCommand.ViewModel)
------------------------------------------------------------------------------
import_state  ARGS: none -> {"folder": scanned folder, "scanning": bool, "files_left_to_scan": int,
              "files": [{"name", "importer" (the importer TBC detected), "folder" (is a sub-folder),
              "already_imported"}], "selected": [names of the files chosen for import]}
import_folder ARGS: folder -> import_state after setting the folder. Setting RequestedPath makes the pane scan
              the folder; the server polls import_state until "scanning" is False (up to 60 s).
import_select ARGS: files [names] -> import_state after selecting exactly those files (case-insensitive names;
              sub-folders can't be selected). Raises, listing up to 40 of the folder's entries, if a name is not
              in the folder.

Export actions (Export pane open; WinForms)
-------------------------------------------
export_formats ARGS: category (optional tab text) -> {tab text: [exporter names]} for every format category tab,
               or only the matching one ({} when nothing matches). Briefly selects each tab to read its list,
               then reselects the tab that was selected before.
export_choose  ARGS: category, format -> {"category", "format"} after selecting that tab and exporter
               (case-insensitive). Raises with the available categories / exporters when one doesn't exist.

Nothing here presses Import or Export or changes the project: the server presses the button through command_ui
(so popups, the Import Format Editor wizard and Compute Project waits are handled the usual way). Importing changes
the project and TBC copies every imported file into the project folder, so the server requires confirm=true.
"""
import clr
import System
from System.Reflection import BindingFlags as BF

# CommandHost manages TBC's command panels; read once per call (the module runs fresh each time).
ui_host = TrimbleOffice.TheOffice.MainForm.CommandHost


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------
def _top():
    """The command whose panel is on top (CommandHost.TopCommand). Raises "No command is open" if none."""
    tc = ui_host.TopCommand
    if tc is None:
        raise Exception("No command is open")
    return tc


# ------------------------------------------------------------------ import
def _import_parts():
    """Return (ImportCommand, its ViewModel, its DataGridViewAdapter) for the open Import pane.

    The open command object doesn't expose the ImportCommand publicly: on 2026.10 it sits in a non-public instance
    field named "a", read here by reflection (BindingFlags Instance | NonPublic). Such a field name can differ in
    another TBC release. The type name check makes sure the open pane really is Import. DataGridViewAdapter (the
    pane's file grid) is read the same way, public or not.
    Raises "The Import pane is not the open command" otherwise.
    """
    tc = _top()
    f = tc.GetType().GetField("a", BF.Instance | BF.NonPublic)
    ic = f.GetValue(tc) if f is not None else None
    if ic is None or ic.GetType().Name != "ImportCommand":
        raise Exception("The Import pane is not the open command")
    dg = ic.GetType().GetField("DataGridViewAdapter", BF.Instance | BF.Public | BF.NonPublic).GetValue(ic)
    return ic, ic.ViewModel, dg


def _name(item):
    """File name (no folder) of an Import pane grid item, from its full Path."""
    return System.IO.Path.GetFileName(str(item.Path))


def import_state(args):
    """ACTION "import_state": the pane's folder, scan progress, file grid and selection (shape in the module docstring).

    "importer" is TBC's detected importer for each file; the home_import_export skill notes it can be wrong (a
    P,N,E file was detected with easting/northing swapped), so it is shown to the user before importing.
    """
    ic, vm, dg = _import_parts()
    return {"folder": str(vm.RequestedPath or ""), "scanning": bool(vm.ImporterScanningInProgress),
            "files_left_to_scan": int(vm.FilesLeftToScan),
            "files": [{"name": _name(i), "importer": str(i.CalculatedImporterText or ""), "folder": bool(i.IsFolder),
                       "already_imported": bool(i.IsImported)} for i in dg.Items],
            "selected": [_name(i) for i in vm.FilesToImport]}


def import_folder(args):
    """ACTION "import_folder": point the pane at args["folder"] (it starts scanning) and return import_state.

    Set through the pane's own view model (RequestedPath) instead of typing into the UI.
    The returned state is usually still scanning.
    """
    ic, vm, dg = _import_parts()
    vm.RequestedPath = str(args["folder"])
    return import_state(args)


def import_select(args):
    """ACTION "import_select": select exactly args["files"] (file names) in the pane's grid, return import_state.

    Matching is case-insensitive on the file name and skips sub-folder entries. All names must exist, otherwise
    nothing is selected and the error lists what is missing and (up to 40) what is there. Selection goes through
    the pane's grid adapter (SetSelection); import_state then reports it from the view model's FilesToImport.
    """
    ic, vm, dg = _import_parts()
    want = [str(x).lower() for x in args.get("files", [])]
    hit = [i for i in dg.Items if _name(i).lower() in want and not bool(i.IsFolder)]
    missing = [x for x in args.get("files", []) if str(x).lower() not in [_name(i).lower() for i in hit]]
    if missing:
        raise Exception("Not in the import folder: %s (files there: %s)" % (missing, [_name(i) for i in dg.Items][:40]))
    dg.SetSelection(hit)
    return import_state(args)


# ------------------------------------------------------------------ export
def _find(c, n):
    """Depth-first search of WinForms control `c` and its children for the control named `n`; None if absent."""
    if c.Name == n:
        return c
    for k in c.Controls:
        r = _find(k, n)
        if r is not None:
            return r
    return None


def _export_parts():
    """Return (panel, GroupTab, FormatList) of the open Export pane.

    The open command's CommandUI is the WinForms panel. "GroupTab" is the format category tab strip (an
    Infragistics UltraTabStrip, per the home_import_export skill) and "FormatList" the exporter list box; both are
    found by control Name. Raises "The Export pane is not the open command" if either is missing.
    """
    ui = _top().CommandUI
    gt, fl = _find(ui, "GroupTab"), _find(ui, "FormatList")
    if gt is None or fl is None:
        raise Exception("The Export pane is not the open command")
    return ui, gt, fl


def export_formats(args):
    """ACTION "export_formats": {category tab text: [exporter names]} (optionally one category).

    FormatList only shows the exporters of the selected tab, so each tab is selected in turn and read with
    GetItemText (the text the list displays). The originally selected tab is restored at the end.
    """
    ui, gt, fl = _export_parts()
    cur = gt.SelectedTab
    out = {}
    for t in gt.Tabs:
        if args.get("category") and str(t.Text).lower() != str(args["category"]).lower():
            continue
        gt.SelectedTab = t
        out[str(t.Text)] = [str(fl.GetItemText(i)) for i in fl.Items]
    gt.SelectedTab = cur
    return out


def export_choose(args):
    """ACTION "export_choose": select category tab args["category"] and exporter args["format"].

    Both matched case-insensitively against the displayed text; the first match wins. The list's selection is
    cleared (ClearSelected), then SelectedIndex is set to the exporter. The pane then rebuilds its
    fields for that exporter; the server waits briefly and fills the target file and data box afterwards.
    Returns {"category", "format"} as TBC shows them.
    """
    ui, gt, fl = _export_parts()
    tabs = [t for t in gt.Tabs if str(t.Text).lower() == str(args["category"]).lower()]
    if not tabs:
        raise Exception("No format category '%s'. Categories: %s" % (args["category"], [str(t.Text) for t in gt.Tabs]))
    gt.SelectedTab = tabs[0]
    names = [str(fl.GetItemText(i)) for i in fl.Items]
    want = str(args["format"]).lower()
    idx = [k for k, n in enumerate(names) if n.lower() == want]
    if not idx:
        raise Exception("No exporter '%s' in %s. Exporters: %s" % (args["format"], tabs[0].Text, names))
    fl.ClearSelected()
    fl.SelectedIndex = idx[0]
    return {"category": str(gt.SelectedTab.Text), "format": names[idx[0]]}


# Dispatch: the server prepends ACTION/ARGS; the bridge returns `result`. An unknown ACTION raises KeyError.
result = {"import_state": import_state, "import_folder": import_folder, "import_select": import_select,
          "export_formats": export_formats, "export_choose": export_choose}[ACTION](ARGS)
