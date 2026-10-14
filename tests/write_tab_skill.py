# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Turn a <tab>_tab_survey.json into knowledge/skills/<category>/<tab>_tab_overview.skill.md.
Usage: py -3.12 write_tab_skill.py <tab> <category> [notes.json]
notes.json (optional): {"<command key>": "extra note shown in the 'opens' column"}"""
import json, os, sys

here = os.path.dirname(os.path.abspath(__file__))
tab, category = sys.argv[1].lower(), sys.argv[2]
notes = json.load(open(sys.argv[3], encoding="utf-8-sig")) if len(sys.argv) > 3 else {}
intro = notes.pop("_intro", [])
d = json.load(open(os.path.join(here, "tab_data", "%s_tab_survey.json" % tab)))

rel = d.get("tbc_version", "2026.10")
L = ["---", "name: %s_tab_overview" % tab, "tbc_versions: [\"%s\"]" % rel, "category: %s" % category,
     'description: "Every tool on the TBC 2026 %s ribbon tab: what it does (from TBC help), command key, help topic, '
     'license, what opens (panel fields/buttons, dialog, view window), and which tools act immediately."' % d["tab"],
     "requires_write: false", "parameters: []",
     'verified: "2026-10-13 live survey on TBC 2026.10 (opened with nothing selected, nothing applied)"', "---",
     "", "> Verified on TBC %s. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the %s information." % (rel, rel), "",
     "## Read first", "",
     "- Read a tool's help before using it: `tbc_help action=read command=<key>` (or the topic number below).",
     "- LICENSES DIFFER between users: the license column reflects the machine that ran this survey; check yours with `tbc_license`."] + intro + [""]
group = None
for r in d["results"]:
    if r["group"] != group:
        group = r["group"]
        L += ["", "### " + group, "", "| tool | key / help | what it does | opens |", "|---|---|---|---|"]
    o = r["outcome"]
    if o == "panel":
        o = "panel: %s. Buttons: %s" % (", ".join(f for f in r.get("fields", []) if f) or "no fields", ", ".join(b for b in r.get("buttons", []) if b))
    elif o == "dialog":
        o = 'dialog "%s"' % (r.get("dialogs") or [{}])[0].get("title")
    elif o.startswith("opens"):
        o = "view window: " + ", ".join(r.get("windows", []) + r.get("panes", []))
    n = notes.get(r["key"])
    if n:
        o = n if o.startswith("excluded") else n + " " + o
    what = (r.get("help_summary") or "").replace("|", "/").replace("\n", " ")
    if len(what) > 230:
        what = what[:227] + "..."
    L.append("| %s | `%s` / %s | %s | %s |" % (r["caption"], r["key"], r.get("help_topic") or "-", what, o.replace("|", "/")))
out = os.path.join(here, "..", "knowledge", "skills", category, "%s_tab_overview.skill.md" % tab)
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
print("wrote", out, len(L), "lines")
