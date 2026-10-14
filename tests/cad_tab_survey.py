# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Survey pass over every tool on TBC's CAD ribbon tab: open it with nothing selected, record what appears
(panel fields/buttons, TBC popup, Windows dialog, or nothing), then close it without applying anything.
Checks the project's 'modified' flag before/after as a tripwire. Writes tests/tab_data/cad_tab_survey.json.
Usage: python cad_tab_survey.py   (TBC running, bridge ON, project saved)
"""
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "mcp_server"))
import tbc_mcp_server as S
import knowledge as K

tab = json.load(open(os.path.join(here, "tab_data", "cad_tab_tools.json")))
tools = []
for g in tab["groups"]:
    for t in g["tools"]:
        for x in [t] + t.get("children", []):
            x = dict(x)
            if x["key"].startswith("DuplicateCmd."):  # ribbon duplicates: "DuplicateCmd.1.<RealKey>"
                x["key"] = x["key"].split(".", 2)[2]
            tools.append((g["group"], x))

class Abort(Exception):
    pass


def dismiss_everything():
    """One safe pass (Cancel/Close/No or X only). If anything is still open, abort the whole survey."""
    acts = S.safe_dismiss()
    left = [a for a in acts if a.get("still_open")]
    if left:
        raise Abort("popups could not be closed safely: %s" % left)
    return acts


def close_command():
    try:
        S.run_ipy("command_ui", "close", {"all": True})
    except S.BridgeError:
        pass


def info():
    i = S.call_bridge("project_info")
    return i["modified"], i["point_count"], i["worldview_top_level_count"]


S.call_bridge("set_selection", {"serials": []})
close_command()
start = info()
print("start: modified=%s points=%s top=%s" % start)
results = []
for group, t in tools:
    key, cap = t["key"], t["caption"]
    rec = {"group": group, "caption": cap, "key": key, "type": t["type"]}
    if not t["enabled"]:
        rec["outcome"] = "disabled on ribbon (skipped)"
        results.append(rec)
        print("%-22s %-28s %s" % (group, cap, rec["outcome"]))
        continue
    lic = S.run_ipy("command_ui", "license", {"keys": [key]}).get(key, {})
    if lic.get("licensed") is False:
        rec["outcome"] = "not licensed (skipped, needs one of %s)" % lic.get("needs_any_of")
        results.append(rec)
        print("%-22s %-28s %s" % (group, cap, rec["outcome"]))
        continue
    try:
        st = S.t_command_ui_open({"key": key, "wait_seconds": 6})
        ds = [] if st.get("not_licensed") else (st.get("dialogs") or S.dialogs_snapshot())
        if st.get("not_licensed"):
            rec["outcome"] = "not licensed (TBC popup closed with X)"
            rec["license_problem"] = st.get("license_problem")
        elif st.get("command"):
            rec["outcome"] = "panel"
            rec["panel"] = st["command"]["caption"]
            rec["fields"] = ["%s [%s]" % (f.get("label") or f["id"], f["kind"]) for f in st.get("fields", [])]
            rec["buttons"] = [b["text"] for b in st.get("buttons", [])]
        elif ds:
            rec["outcome"] = "dialog"
        else:
            rec["outcome"] = "no panel/dialog (acts directly, toggles a pane, or needs a selection)"
        if ds:
            rec["dialogs"] = [{"title": d.get("title"), "message": (d.get("message") or "")[:200],
                               "buttons": d.get("buttons"), "native": bool(d.get("native"))} for d in ds]
    except Exception as ex:
        rec["outcome"] = "error"
        rec["error"] = str(ex)[:300]
    try:
        acts = dismiss_everything()
        if acts:
            rec["dismissed"] = acts
    except Abort as ex:
        rec["outcome"] = "ABORTED: %s" % ex
        results.append(rec)
        print("ABORTING SURVEY:", ex)
        break
    close_command()
    if t["type"] == "StateButtonTool":  # toggles a docked pane: toggle it back
        S.call_bridge("run_command", {"key": key})
        time.sleep(1.5)
        rec["note"] = "toggle; ran twice to restore"
    m = info()
    rec["modified_after"] = m[0]
    results.append(rec)
    extra = rec.get("panel") or (rec.get("dialogs") or [{}])[0].get("title") or rec.get("error", "")
    print("%-22s %-28s %-10s %s%s" % (group, cap, rec["outcome"].split(" ")[0], extra,
                                      "  <-- PROJECT MODIFIED" if m[0] and not start[0] else ""))

end = info()
print("end:   modified=%s points=%s top=%s" % end)
json.dump({"start": start, "end": end, "results": results}, open(os.path.join(here, "tab_data", "cad_tab_survey.json"), "w"), indent=1)
