# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Turn a <tab>_tab_survey.json into knowledge/skills/<category>/<tab>_tab_overview.skill.md.
Usage: py -3.12 write_tab_skill.py <tab> <category> [notes.json]
notes.json (optional): {"<command key>": "extra note shown in the 'opens' column"}

Second half of the ribbon-tab survey workflow: tests\\tab_survey.py records a tab into
tests\\tab_data\\<tab>_tab_survey.json, and this script writes the matching overview skill for the knowledge
base (one markdown table per ribbon group: tool, command key / help topic, what it does, what opens).

Needs TBC
    No. Offline: it only reads the survey JSON (and the optional notes file) and writes one markdown file.

How to run (example)
    py -3.12 tests\\write_tab_skill.py linework linework tests\\tab_data\\linework_tab_notes.json
    <tab> is lower-cased and must match tests\\tab_data\\<tab>_tab_survey.json; <category> is the skills
    sub-folder. In notes.json the special key "_intro" holds extra bullet lines added under "Read first";
    a note for a tool whose outcome is "excluded" replaces the outcome, otherwise it is prepended to it.

What it writes
    knowledge\\skills\\<category>\\<tab>_tab_overview.skill.md, overwritten whole, with frontmatter
    (tbc_versions taken from the survey's "tbc_version", default 2026.10) and the version banner the
    knowledge base uses. The "verified" date in the frontmatter is a fixed string, not today's date.
    The tab's display name comes from the survey's "tab" key (tab_survey.py and cad_tab_survey.py write it),
    else from the <tab> argument, upper-cased.

Pass / fail
    Prints "wrote <path> <n> lines"; any error is a Python exception.
"""
import json, os, sys

here = os.path.dirname(os.path.abspath(__file__))
tab, category = sys.argv[1].lower(), sys.argv[2]
notes = json.load(open(sys.argv[3], encoding="utf-8-sig")) if len(sys.argv) > 3 else {}
intro = notes.pop("_intro", [])
d = json.load(open(os.path.join(here, "tab_data", "%s_tab_survey.json" % tab)))

rel = d.get("tbc_version", "2026.10")
# L collects the output lines: YAML frontmatter, version banner, "Read first" bullets, then the tables
L = ["---", "name: %s_tab_overview" % tab, "tbc_versions: [\"%s\"]" % rel, "category: %s" % category,
     'description: "Every tool on the TBC 2026 %s ribbon tab: what it does (from TBC help), command key, help topic, '
     'license, what opens (panel fields/buttons, dialog, view window), and which tools act immediately."' % d.get("tab", tab.upper()),
     "requires_write: false", "parameters: []",
     'verified: "2026-10-13 live survey on TBC 2026.10 (opened with nothing selected, nothing applied)"', "---",
     "", "> Verified on TBC %s. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the %s information." % (rel, rel), "",
     "## Read first", "",
     "- Read a tool's help before using it: `tbc_help action=read command=<key>` (or the topic number below).",
     "- LICENSES DIFFER between users: the license column reflects the machine that ran this survey; check yours with `tbc_license`."] + intro + [""]
# one table per ribbon group, started whenever the group changes (results are in ribbon order)
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
    # "|" would break the markdown table, so it is replaced; long help summaries are cut to 230 chars
    what = (r.get("help_summary") or "").replace("|", "/").replace("\n", " ")
    if len(what) > 230:
        what = what[:227] + "..."
    L.append("| %s | `%s` / %s | %s | %s |" % (r["caption"], r["key"], r.get("help_topic") or "-", what, o.replace("|", "/")))
out = os.path.join(here, "..", "knowledge", "skills", category, "%s_tab_overview.skill.md" % tab)
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
print("wrote", out, len(L), "lines")
