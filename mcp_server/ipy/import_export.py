# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# IronPython 3.4 code executed INSIDE TBC by the MCP server. Prepended: ACTION, ARGS. Sets `result`.
# Drives the Home tab's Import pane (WPF, ImportCommand view model) and Export pane (WinForms) the way the panes
# themselves do: folder + file selection through the pane's own view model / grid adapter, format tabs and lists
# through their controls. Pressing Import / Export is left to command_ui (so popups are handled the usual way).
import clr
import System
from System.Reflection import BindingFlags as BF

ui_host = TrimbleOffice.TheOffice.MainForm.CommandHost


def _top():
    tc = ui_host.TopCommand
    if tc is None:
        raise Exception("No command is open")
    return tc


# ------------------------------------------------------------------ import
def _import_parts():
    tc = _top()
    f = tc.GetType().GetField("a", BF.Instance | BF.NonPublic)
    ic = f.GetValue(tc) if f is not None else None
    if ic is None or ic.GetType().Name != "ImportCommand":
        raise Exception("The Import pane is not the open command")
    dg = ic.GetType().GetField("DataGridViewAdapter", BF.Instance | BF.Public | BF.NonPublic).GetValue(ic)
    return ic, ic.ViewModel, dg


def _name(item):
    return System.IO.Path.GetFileName(str(item.Path))


def import_state(args):
    ic, vm, dg = _import_parts()
    return {"folder": str(vm.RequestedPath or ""), "scanning": bool(vm.ImporterScanningInProgress),
            "files_left_to_scan": int(vm.FilesLeftToScan),
            "files": [{"name": _name(i), "importer": str(i.CalculatedImporterText or ""), "folder": bool(i.IsFolder),
                       "already_imported": bool(i.IsImported)} for i in dg.Items],
            "selected": [_name(i) for i in vm.FilesToImport]}


def import_folder(args):
    ic, vm, dg = _import_parts()
    vm.RequestedPath = str(args["folder"])
    return import_state(args)


def import_select(args):
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
    if c.Name == n:
        return c
    for k in c.Controls:
        r = _find(k, n)
        if r is not None:
            return r
    return None


def _export_parts():
    ui = _top().CommandUI
    gt, fl = _find(ui, "GroupTab"), _find(ui, "FormatList")
    if gt is None or fl is None:
        raise Exception("The Export pane is not the open command")
    return ui, gt, fl


def export_formats(args):
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


result = {"import_state": import_state, "import_folder": import_folder, "import_select": import_select,
          "export_formats": export_formats, "export_choose": export_choose}[ACTION](ARGS)
