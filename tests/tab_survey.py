# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Generic survey pass over one TBC ribbon tab: for every licensed, enabled tool (minus exclusions) open it with
nothing selected, record what appears (panel fields/buttons, popup, new view window, pane), then close it
WITHOUT applying anything. Paced (the server enforces a gap between command launches; this script adds a pause).
Usage: python tab_survey.py <TabKey> [--exclude key1,key2] [--only key1,key2]
Writes tests/tab_data/<tab>_tab_tools.json and tests/tab_data/<tab>_tab_survey.json.

Part of the "Tested tab by tab" workflow (README): this surveyor records every button of a ribbon tab, then
tests\\write_tab_skill.py turns the survey JSON into knowledge\\skills\\<category>\\<tab>_tab_overview.skill.md.

Needs TBC
    Yes: TBC 2026.10 with a project open and the MCP Bridge macro on. Save the project first: the survey
    watches the project's "modified" flag and object counts as a tripwire and flags any tool that changed them.
    Reads the installed TBC help (mcp_server\\tbc_help.py) for each tool's help summary.

How to run
    py -3.12 tests\\tab_survey.py <TabKey> [--exclude key1,key2] [--only key1,key2]
    <TabKey> is the ribbon tab's internal Key (as stored in AppToolbar.Ribbon.Tabs), not its caption; the
    output files use it lower-cased. --exclude lists command keys known to act immediately (they are recorded
    as "excluded" without being opened); --only surveys just these keys.

What it creates and cleans up
    Nothing is applied. After each tool: popups are closed the safe way, the panel is closed, new view
    windows are closed, and panes the command opened are closed by running the command again. If a popup
    can't be closed safely the survey stops ("ABORTING").

What it writes
    tests\\tab_data\\<tab>_tab_tools.json   the tab's groups and tools (key, caption, type, enabled, help topic)
    tests\\tab_data\\<tab>_tab_survey.json  one record per tool: outcome (panel / dialog / opens a view window /
                                          opens a pane / no panel / excluded / not licensed / disabled / error),
                                          panel fields and buttons, popups, help title and summary,
                                          modified_after. Rewritten after every tool with "partial": true so
                                          a TBC crash keeps what was gathered; the final write adds the TBC
                                          release and build and the end state.

Pass / fail
    Not a pass/fail test: it is a recorder. Read the console for "PROJECT BECAME MODIFIED" or "COUNTS
    CHANGED" flags and for errors.
"""
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
# import the MCP server module (and its offline help reader) in-process
sys.path.insert(0, os.path.join(here, "..", "mcp_server"))
import tbc_mcp_server as S
import tbc_help as H

tab_key = sys.argv[1]
# command keys (lower case) to skip without opening / to survey exclusively
excl = set()
only = set()
for i, a in enumerate(sys.argv):
    if a == "--exclude":
        excl = set(k.strip().lower() for k in sys.argv[i + 1].split(","))
    if a == "--only":
        only = set(k.strip().lower() for k in sys.argv[i + 1].split(","))

# IronPython run inside TBC with args = the tab key: walk the ribbon (MainForm.AppToolbar) and return every group and tool with its key, caption ('&' accelerators removed), tool type, enabled
# state and the help topic of the matching entry in TBC's command list. Keys of ribbon duplicates
# ("DuplicateCmd.<n>.<RealKey>") are reduced to the real key; popup/gallery tools list their children.
TAB_CODE = r"""
tm = TrimbleOffice.TheOffice.MainForm.AppToolbar
tab = [t for t in tm.Ribbon.Tabs if str(t.Key) == args][0]
cl = TrimbleOffice.TheOffice.CommandProcessor.CommandList
def info(tool):
    sp = tool.SharedProps
    k = str(tool.Key)
    if k.startswith('DuplicateCmd.'): k = k.split('.', 2)[2]
    d = {'key': k, 'caption': str(sp.Caption).replace('&', ''), 'type': tool.GetType().Name, 'enabled': bool(sp.Enabled)}
    if cl.ContainsKey(k.lower()):
        d['help'] = str(getattr(cl[k.lower()], 'HelpTopic', '') or '')
    if tool.GetType().Name in ('PopupMenuTool', 'PopupGalleryTool', 'PopupControlContainerTool'):
        try: d['children'] = [info(c) for c in tool.Tools]
        except: pass
    return d
result = {'tab': str(tab.Caption), 'groups': [{'group': str(g.Caption).replace('&', ''), 'tools': [info(t) for t in g.Tools]} for g in tab.Groups]}
"""
tab = S.call_bridge("execute_python", {"code": "args = %r\n" % tab_key + TAB_CODE, "transaction": False})["result"]
json.dump(tab, open(os.path.join(here, "tab_data", "%s_tab_tools.json" % tab_key.lower()), "w"), indent=1)

# flatten to (group, tool) pairs, children of popup tools included; LabelTool entries are captions, not commands
tools = []
for g in tab["groups"]:
    for t in g["tools"]:
        for x in [t] + t.get("children", []):
            if x["type"] != "LabelTool":
                tools.append((g["group"], x))
# one silent license check for every key (no TBC license popups): {key: {"exists", "licensed", "needs_any_of"}}
lic = S.run_ipy("command_ui", "license", {"keys": [t["key"] for _, t in tools]})


def help_summary(tid):
    """(title, first substantial sentence) of help topic `tid` from the installed TBC help, or (None, None).

    "Substantial" = the first line over 40 characters that isn't a "Prerequisites" line, cut to 400 chars.
    """
    d = H.topic(tid, 4000) if tid else None
    if not d:
        return None, None
    lines = [l.strip() for l in d["text"].split("\n") if len(l.strip()) > 40 and not l.strip().startswith("Prerequisites")]
    return d["title"], (lines[0] if lines else "")[:400]


def info():
    """Tripwire state: (project modified flag, point count, number of top-level objects)."""
    i = S.call_bridge("project_info")
    return i["modified"], i["point_count"], i["worldview_top_level_count"]


# start clean: nothing selected, no panel open; remember which windows and panes were already open
S.call_bridge("set_selection", {"serials": []})
try:
    S.run_ipy("command_ui", "close", {"all": True})
except S.BridgeError:
    pass
start = info()
base_forms = set(f["id"] for f in S.run_ipy("command_ui", "forms", {}))
base_panes = set(p["title"] for p in S.ui_state(include_text=False)["panes"] if p["open"])
print("start: modified=%s points=%s top=%s | windows %d | panes %s" % (start + (len(base_forms), sorted(base_panes))))
results = []
for group, t in tools:
    key, cap = t["key"], t["caption"]
    rec = {"group": group, "caption": cap, "key": key, "type": t["type"], "help_topic": t.get("help")}
    rec["help_title"], rec["help_summary"] = help_summary(t.get("help"))
    l = lic.get(key, {})
    if only and key.lower() not in only:
        continue
    # tools that are not opened at all are recorded with the reason
    if key.lower() in excl:
        rec["outcome"] = "excluded (acts immediately or not safe to open; see help)"
    elif l.get("exists") is False:
        rec["outcome"] = "no command key"
    elif l.get("licensed") is False:
        rec["outcome"] = "not licensed (needs one of %s)" % l.get("needs_any_of")
    elif not t["enabled"]:
        rec["outcome"] = "disabled on ribbon in this project"
    if "outcome" in rec:
        results.append(rec)
        print("%-12s %-28s %s" % (group, cap, rec["outcome"]))
        continue
    try:
        # open the tool with nothing selected (license check, pacing and waits come from the server);
        # then classify what appeared: a panel, a popup, a new view window or a new pane
        st = S.t_command_ui_open({"key": key, "wait_seconds": 15})
        ds = [] if st.get("not_licensed") else (st.get("dialogs") or S.dialogs_snapshot())
        new_forms = [f for f in S.run_ipy("command_ui", "forms", {}) if f["id"] not in base_forms and not f["modal"]]
        new_panes = [p["title"] for p in S.ui_state(include_text=False)["panes"] if p["open"] and p["title"] not in base_panes]
        if st.get("not_licensed"):
            rec["outcome"] = "not licensed (TBC popup closed with X)"
        elif st.get("command"):
            rec["outcome"] = "panel"
            rec["panel"] = st["command"]["caption"]
            rec["fields"] = ["%s [%s]" % (f.get("label") or f["id"], f["kind"]) for f in st.get("fields", [])]
            rec["buttons"] = [b["text"] for b in st.get("buttons", [])]
        elif ds:
            rec["outcome"] = "dialog"
        elif new_forms:
            rec["outcome"] = "opens a view window"
        elif new_panes:
            rec["outcome"] = "opens a pane"
        else:
            rec["outcome"] = "no panel/dialog/window (acts directly or needs a selection)"
        if ds:
            rec["dialogs"] = []
            for d in ds:
                rec["dialogs"].append({"title": d.get("title"), "message": (d.get("message") or "")[:300],
                                       "fields": ["%s [%s]" % (f.get("label") or f.get("id"), f.get("kind")) for f in d.get("fields", [])][:25],
                                       "buttons": d.get("buttons"), "native": bool(d.get("native"))})
        if new_forms:
            rec["windows"] = [f["title"] for f in new_forms]
        if new_panes:
            rec["panes"] = new_panes
    except Exception as ex:
        rec["outcome"] = "error"
        rec["error"] = str(ex)[:300]
        new_forms, new_panes = [], []
    time.sleep(1.5)  # popups such as 'Feature Library Missing' can appear a moment after the panel
    late = S.dialogs_snapshot()
    if late and not rec.get("dialogs"):
        rec["dialogs"] = [{"title": d.get("title"), "message": (d.get("message") or "")[:300], "buttons": d.get("buttons"),
                           "native": bool(d.get("native"))} for d in late]
    # one safe pass over the popups (Cancel/Close/No or X); stop the survey if any stays open
    acts = S.safe_dismiss(late)
    if acts:
        rec["dismissed"] = acts
        if any(a.get("still_open") for a in acts):
            results.append(rec)
            print("ABORTING: popups could not be closed safely:", acts)
            break
    try:
        S.run_ipy("command_ui", "close", {"all": True})
    except S.BridgeError:
        pass
    left_forms = [f for f in S.run_ipy("command_ui", "forms", {}) if f["id"] not in base_forms and not f["modal"]]
    if left_forms:
        S.run_ipy("command_ui", "close_forms", {"ids": [f["id"] for f in left_forms]})
        time.sleep(1.0)
    # docked panes are toggled by their command: running it again closes the pane it opened
    for p in [p["title"] for p in S.ui_state(include_text=False)["panes"] if p["open"] and p["title"] not in base_panes]:
        rec.setdefault("note", "pane '%s' left open by the command; closed by toggling the command" % p)
        S.t_run_command({"key": key})
        time.sleep(1.5)
    m = info()
    rec["modified_after"] = m[0]
    results.append(rec)
    json.dump({"tab": tab_key, "start": start, "results": results, "partial": True},
              open(os.path.join(here, "tab_data", "%s_tab_survey.json" % tab_key.lower()), "w"), indent=1)  # survive a crash
    # console line: group, caption, first word of the outcome, what opened, and tripwire flags
    extra = rec.get("panel") or (rec.get("dialogs") or [{}])[0].get("title") or ", ".join(rec.get("windows", []) + rec.get("panes", [])) or rec.get("error", "")
    flag = "  <-- PROJECT BECAME MODIFIED" if m[0] and not start[0] else ""
    flag += "  <-- COUNTS CHANGED" if m[1:] != start[1:] else ""
    print("%-12s %-28s %-8s %s%s" % (group, cap, rec["outcome"].split(" ")[0], extra, flag))
    time.sleep(1.0)  # pacing between commands (user preference)

end = info()
print("end:   modified=%s points=%s top=%s" % end)
print("windows left over:", [f for f in S.run_ipy("command_ui", "forms", {}) if f["id"] not in base_forms])
# final write: replaces the partial file, adds the TBC release/build the survey was taken on (the overview
# skill's tbc_versions comes from this) and drops the "partial" flag
ver = S.tbc_version()
json.dump({"tab": tab_key, "tbc_version": ver["release"], "tbc_build": ver["build"], "start": start, "end": end, "results": results},
          open(os.path.join(here, "tab_data", "%s_tab_survey.json" % tab_key.lower()), "w"), indent=1)
