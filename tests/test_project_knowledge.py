# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Tests the knowledge base without TBC: the project knowledge shared with Civil 3D MCP and Project Analyzer
(mcp_server/projects.py) and the general-knowledge rules (duplicate checks, lessons surfacing by command).
Everything runs in a temporary folder; the real knowledge bases are never touched.
Usage: python test_project_knowledge.py
"""
import json, os, shutil, subprocess, sys, tempfile, textwrap

here = os.path.dirname(os.path.abspath(__file__))
server = os.path.join(here, "..", "mcp_server", "tbc_mcp_server.py")
work = tempfile.mkdtemp(prefix="tbc_mcp_kb_test_")
# The test folder lives in %TEMP%, which the privacy check refuses to link: point the per-user folders elsewhere
for var in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
    os.environ[var] = os.path.join(work, "private", var)
    os.makedirs(os.environ[var])
os.environ.pop("TBC_MCP_USER_DIR", None)
shared = os.path.join(work, "shared")
general = os.path.join(work, "general")
os.makedirs(os.path.join(general, "commands"))
with open(os.path.join(general, "commands", "createlinestring.json"), "w") as f:
    json.dump({"key": "createlinestring", "fields": [], "buttons": [], "notes": []}, f)
os.environ["CIVIL3D_KNOWLEDGE_DIR"] = shared
os.environ["TBC_MCP_KNOWLEDGE_DIR"] = general
sys.path.insert(0, os.path.join(here, "..", "mcp_server"))
import knowledge as K  # noqa: E402
import projects as P  # noqa: E402

ok = True


def check(cond, label):
    global ok
    ok = ok and bool(cond)
    print(("PASS " if cond else "FAIL ") + label)


def raises(fn, text):
    try:
        fn()
    except K.KnowledgeError as ex:
        return text.lower() in str(ex).lower()
    return False


job = os.path.join(work, "jobs", "Elm Street")
os.makedirs(os.path.join(job, "TBC", "Phase 2"))
vce = os.path.join(job, "TBC", "Elm Street.vce")
deep_vce = os.path.join(job, "TBC", "Phase 2", "Phase 2.vce")

# --- 1. a job set up by Civil 3D MCP (written the way projectNotes.ts writes it, with a BOM) ------------------
check(P.slug("Elm Street Drainage") == "elm-street-drainage" and P.slug("  --A/B 1--  ") == "a-b-1", "slug matches projectNotes.ts")
os.makedirs(os.path.join(shared, "projects"))
c3d = {"name": "Elm Street Drainage", "folders": [job],
       "notes": [{"id": "note-1", "note": "Point group CTRL holds the control points", "added": "2026-10-01T12:00:00.000Z"}]}
with open(os.path.join(shared, "projects", "elm-street-drainage.json"), "w", encoding="utf-8-sig") as f:
    f.write(json.dumps(c3d, indent=2) + "\n")
check((P.project_for_path(vce) or {}).get("name") == "Elm Street Drainage", "open .vce in a subfolder matches the job's folder")
check(P.project_for_path(os.path.join(work, "elsewhere", "x.vce")) is None, "a .vce outside every linked folder matches nothing")
check(P.project_for_path("Untitled") is None, "an unsaved project matches nothing")

# --- 2. TBC adds notes in the same format -------------------------------------------------------------------
r = P.add_note("Surface FG is the design\nfinish grade", None, vce)
check(r["action"] == "added" and r["note"]["id"] == "note-2" and r["note"]["source"] == "tbc", "add -> note-2, marked source=tbc")
check(r["note"]["note"] == "Surface FG is the design finish grade", "notes are one line")
check(r["note"]["added"].endswith("Z") and len(r["note"]["added"]) == 24, "timestamps in toISOString form")
check(P.add_note("surface fg is the design finish grade", None, vce)["action"] == "unchanged", "duplicate (any case) not stored twice")
with open(os.path.join(shared, "projects", "elm-street-drainage.json"), encoding="utf-8") as f:
    raw = f.read()
data = json.loads(raw)
check(list(data) == ["name", "folders", "notes"] and len(data["notes"]) == 2, "file keeps Civil 3D MCP's shape: name, folders, notes")
check(not raw.startswith("﻿") and raw.endswith("}\n"), "written as UTF-8 JSON with a final newline")
check(not [n for n in os.listdir(os.path.join(shared, "projects")) if n.endswith(".tmp")], "no temp files left behind")

# --- 3. ownership: TBC changes only its own notes ------------------------------------------------------------
check(raises(lambda: P.update_note("note-1", "changed", None, vce), "civil 3d mcp"), "a Civil 3D note can't be updated")
check(raises(lambda: P.remove_note("note-1", None, vce), "civil 3d mcp"), "a Civil 3D note can't be removed")
check(P.update_note("note-2", "Surface FG is finish grade", None, vce)["note"].get("updated"), "own note updated, with 'updated'")
data["notes"].append({"id": "note-3", "note": "Owner is the City (2026-03-04) [source: contract.pdf; fact-12]", "added": "2026-10-02T00:00:00.000Z"})
with open(os.path.join(shared, "projects", "elm-street-drainage.json"), "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
listed = P.list_notes(None, vce)
by = {n["id"]: n["by"] for n in listed["notes"]}
check(by == {"note-1": "civil3d", "note-2": "tbc", "note-3": "project-analyzer"}, "each note says which tool wrote it: %s" % by)
check(raises(lambda: P.remove_note("note-3", None, vce), "project analyzer"), "a Project Analyzer note can't be removed")
check(P.add_note("Phase 2 uses the same control", None, vce)["note"]["id"] == "note-4", "ids continue after other tools' notes")
check(P.remove_note("note-4", None, vce)["action"] == "removed", "own note removed")

# --- 4. link / unlink, deepest folder wins --------------------------------------------------------------------
check(raises(lambda: P.add_note("x", None, os.path.join(work, "nowhere", "a.vce")), "action=link"), "unknown folder -> asks to link")
r = P.link("Phase Two", None, deep_vce)
check(r["action"] == "created" and r["folders"] == [os.path.dirname(deep_vce)], "link defaults to the open .vce's folder")
check(P.project_for_path(deep_vce)["name"] == "Phase Two", "deepest linked folder wins")
check(P.link("Phase Two", os.path.dirname(deep_vce) + "\\", deep_vce)["folders"] == [os.path.dirname(deep_vce)], "same folder isn't linked twice")
check(P.unlink("Phase Two", os.path.dirname(deep_vce))["folders"] == [], "unlink keeps the project, drops the folder")
check(P.project_for_path(deep_vce)["name"] == "Elm Street Drainage", "after unlink the outer job matches again")

# --- 5. files folder and Project Analyzer's reports -----------------------------------------------------------
files = P.files_dir("Elm Street Drainage")
os.makedirs(os.path.join(files, "analysis"))
with open(os.path.join(files, "analysis", "OVERVIEW.md"), "w", encoding="utf-8") as f:
    f.write("# Elm Street Drainage\n\nOverview text.\n")
with open(os.path.join(files, "photo.jpg"), "wb") as f:
    f.write(b"\xff\xd8\x00\x00binary")
r = P.project_files(None, vce)
check([x["path"] for x in r["files"]] == [os.path.join("analysis", "OVERVIEW.md"), "photo.jpg"] and "analysis" in r, "files lists the folder and points to the analysis")
check(P.read_file("analysis\\OVERVIEW.md", None, vce)["text"].startswith("# Elm Street"), "read returns a report's text")
check(P.read_file("analysis/OVERVIEW.md", None, vce, max_chars=5).get("truncated"), "long files are cut at max_chars")
check(raises(lambda: P.read_file("..\\..\\elm-street-drainage.json", None, vce), "inside"), "paths outside the files folder are refused")
check(raises(lambda: P.read_file("photo.jpg", None, vce), "isn't a text file"), "binary files are refused")

# --- 6. notes reach the AI once per project ------------------------------------------------------------------
P.reset_announcements()
first = P.notes_once(vce)
check(first and first["project"] == "Elm Street Drainage" and len(first["notes"]) == 3 and "analysis" in first, "first result carries the job's notes")
check(P.notes_once(vce) is None, "...and only once per server run")

# --- 7. legacy Civil 3D MCP folder is moved, as Civil 3D MCP itself does -------------------------------------
docs = os.path.join(work, "Documents")
os.makedirs(os.path.join(docs, "Civil3DMcp", "projects"))
check(P.migrate_legacy_folder(docs) and os.path.isdir(os.path.join(docs, "Civil3DMcp-KnowledgeBase", "projects")), "Documents\\Civil3DMcp moved to Civil3DMcp-KnowledgeBase")
check(P.migrate_legacy_folder(docs) is None, "migration runs only once")

# --- 8. general knowledge: duplicates, lessons surfacing by command ------------------------------------------
l1 = K.add_lesson("Vertices need at least two points", "createlinestring")
check(K.add_lesson("vertices need at least two points ", "other")["action"] == "unchanged", "duplicate lesson not stored twice")
K.add_lesson("Use clr imports first", "import")
rel = K.lessons_relevant_to("r = run('createlinestring')\nimport clr")
check([x["id"] for x in rel] == [l1["id"]], "lessons surface for a command named in code, not for broad topics like 'import'")
p1 = K.add_pref("Use numeric point IDs")
check(K.add_pref("use numeric point ids")["action"] == "unchanged" and len(K.list_prefs()) == 1, "duplicate preference not stored twice")

# --- 9. a job all three tools have written to (contract: project-analyzer docs/shared-project-knowledge.md) ----
three_dir = os.path.join(work, "jobs", "Three Tools")
os.makedirs(os.path.join(three_dir, "CAD"))
three = {"name": "Three Tools", "civil3d_view": {"zoom": 1.5, "layers": ["C-ROAD"]},
         "folders": [os.path.join(three_dir, "CAD")],
         "notes": [
             {"id": "note-1", "note": "Point group Hide holds the shots beyond the right-of-way.", "added": "2026-10-20T10:00:00.000Z", "pinned": True},
             {"id": "note-2", "note": "Müller Surveying set the control (2026-10-03) [source: Documents/minutes.docx; fact-1]",
              "added": "2026-10-25T21:42:47.123Z", "source": "project-analyzer", "confidence": "high"},
             {"id": "note-3", "note": "The TBC project uses the NAD83 Illinois East zone.", "added": "2026-10-21T08:00:00.000Z", "source": "tbc", "tbc_extra": [1, 2.5, None]}],
         "project-analyzer_last_sync": "2026-10-25T21:42:47.123Z"}
three_path = os.path.join(shared, "projects", "three-tools.json")
three_text = json.dumps(three, indent=2, ensure_ascii=False) + "\n"  # the layout JSON.stringify(x, null, 2) writes
with open(three_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(three_text)


def three_now():
    with open(three_path, encoding="utf-8", newline="") as f:
        return f.read()


by = {n["id"]: n["by"] for n in P.list_notes("Three Tools", None)["notes"]}
check(by == {"note-1": "civil3d", "note-2": "project-analyzer", "note-3": "tbc"}, "origin(): no source = civil3d, source fields trusted: %s" % by)
check(P.origin({"note": "Old analyzer note [source: a.pdf; fact-9]"}) == "project-analyzer"
      and P.origin({"note": "x [source: a.pdf; fact-9]", "source": "tbc"}) == "tbc", "text check is only a fallback for notes without a source")
check(raises(lambda: P.update_note("note-1", "x", "Three Tools", None), "civil 3d mcp")
      and raises(lambda: P.remove_note("note-1", "Three Tools", None), "civil 3d mcp"), "update/remove refuse the Civil 3D note")
check(raises(lambda: P.update_note("note-2", "x", "Three Tools", None), "project analyzer")
      and raises(lambda: P.remove_note("note-2", "Three Tools", None), "project analyzer"), "update/remove refuse the Project Analyzer note")
check(three_now() == three_text, "refused changes leave the file untouched")

r = P.add_note("Surface EG comes from the 2026-10-03 survey [source: Three Tools.vce]", "Three Tools", None)
added = textwrap.indent(json.dumps(r["note"], indent=2, ensure_ascii=False), "    ")
after = three_now()
check(r["note"]["id"] == "note-4" and after.replace(",\n" + added, "", 1) == three_text,
      "adding a note keeps every other note and unknown field byte-for-byte")
check(P.update_note("note-3", "The TBC project uses the NAD83 Illinois East (US ft) zone.", "Three Tools", None)["note"]["tbc_extra"] == [1, 2.5, None],
      "updating TBC's own note keeps its unknown fields")

# re-read before writing: a stale copy in memory must not overwrite what another tool wrote since
stale = P.find_project("Three Tools")
disk = json.loads(three_now())
disk["notes"].append({"id": "note-5", "note": "Civil 3D wrote this meanwhile", "added": "2026-10-26T00:00:00.000Z"})
with open(three_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps(disk, indent=2, ensure_ascii=False) + "\n")
real_resolve, P.resolve = P.resolve, lambda name, active: stale
try:
    r = P.add_note("Another TBC fact", "Three Tools", None)
finally:
    P.resolve = real_resolve
ids = [n["id"] for n in json.loads(three_now())["notes"]]
check(r["note"]["id"] == "note-6" and ids == ["note-1", "note-2", "note-3", "note-4", "note-5", "note-6"], "re-reads the file right before writing: %s" % ids)

with open(three_path, "w", encoding="utf-8") as f:
    f.write('{"name": "Three Tools", "notes": [')
check(raises(lambda: P.add_note("x", "Three Tools", None), "can't be read") and three_now() == '{"name": "Three Tools", "notes": [',
      "a file that doesn't parse is never rewritten")
with open(three_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps(disk, indent=2, ensure_ascii=False) + "\n")

# links: a second link of the same folder changes nothing; other tools' folders are never unlinked
tbc_dir = os.path.join(three_dir, "TBC")
os.makedirs(tbc_dir)
check(P.link("Three Tools", tbc_dir, None)["action"] == "linked", "link adds the TBC folder")
before = three_now()
check(P.link("Three Tools", tbc_dir + "\\", None)["action"] == "unchanged" and three_now() == before, "a second link of the same folder changes nothing")
check(P.link("Three Tools", os.path.join(three_dir, "cad"), None)["action"] == "unchanged" and three_now() == before,
      "linking a folder another tool linked changes nothing")
check(raises(lambda: P.unlink("Three Tools", os.path.join(three_dir, "CAD")), "another tool"), "a folder Civil 3D linked can't be unlinked")
check(json.loads(three_now())[P.OWN_FOLDERS] == [tbc_dir], "TBC's own folders are kept in tbc_linked_folders")

# Project Analyzer's reports, including analysis\intel\
intel = os.path.join(P.files_dir("Three Tools"), "analysis", "intel")
os.makedirs(intel)
with open(os.path.join(intel, "ENTITIES.md"), "w", encoding="utf-8") as f:
    f.write("# Entities\n\n## MH-3 (structure)\nAliases: manhole 3. Files: minutes.docx, C-104.pdf\n")
hint = P.project_files("Three Tools", None).get("analysis", "")
check("ENTITIES.md" in hint and "MH-3" in hint, "files points to analysis\\intel\\ENTITIES.md for structures, stations and sheets")

# privacy and reference formats
P.add_private("tok3n-abcdef", "the bridge's session token")
check(raises(lambda: P.add_note("token is tok3n-ABCDEF", "Three Tools", None), "session token"), "a session token is refused")
check(raises(lambda: P.add_note("see %s\\Documents\\x.vce" % os.path.expanduser("~"), "Three Tools", None), "user profile"), "a user-profile path is refused")
check(raises(lambda: P.link("Three Tools", os.path.join(os.environ["LOCALAPPDATA"], "TBC-MCP"), None), "private"), "a per-user folder can't be linked")
loose = "Manhole 3 rim checked on 10/3/26 at Sta. 1250 (sheet C104), CO #4 was 12.5k"
hints = P.format_hints(loose)
check(P.add_note(loose, "Three Tools", None).get("format_hints") and len(hints) == 6,
      "notes in other formats are saved, with reference-format hints: %s" % hints)
check("format_hints" not in P.add_note("MH-3 rim checked 2026-10-03 at 12+50 (C-104), RFI 12, $12,500.00", "Three Tools", None),
      "notes in the suite's formats get no hints")

# --- 10. the server, over stdio, without TBC ------------------------------------------------------------------
env = dict(os.environ, TBC_MCP_INFO=os.path.join(work, "no_bridge.json"), TBC_MCP_EXIT_WITH_TBC="0")
p = subprocess.Popen([sys.executable, server], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     env=env, text=True, encoding="utf-8")


def rpc(i, method, params):
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params}) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())["result"]


init = rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
check("tbc_project_notes" in init["instructions"] and "Use numeric point IDs" in init["instructions"], "instructions explain the two scopes and carry preferences")
names = [t["name"] for t in rpc(2, "tools/list", {})["tools"]]
check("tbc_project_notes" in names, "tbc_project_notes is listed (%d tools)" % len(names))
r = rpc(3, "tools/call", {"name": "tbc_project_notes", "arguments": {"action": "list", "project": "Elm Street Drainage"}})
check(not r["isError"] and json.loads(r["content"][0]["text"])["project"] == "Elm Street Drainage", "a named job is read without TBC")
r = rpc(4, "tools/call", {"name": "tbc_project_notes", "arguments": {"action": "add", "note": "x"}})
check(r["isError"] and "action=link" in r["content"][0]["text"], "no TBC and no project name -> asks for a name to link")
r = rpc(5, "tools/call", {"name": "tbc_project_notes", "arguments": {"action": "read", "project": "Three Tools", "file": "analysis\\intel\\ENTITIES.md"}})
check(not r["isError"] and "MH-3 (structure)" in json.loads(r["content"][0]["text"])["text"], "action=read opens analysis\\intel\\ENTITIES.md")
desc = next(t["description"] for t in rpc(6, "tools/list", {})["tools"] if t["name"] == "tbc_project_notes")
check(all(s in desc for s in ("12+50", "MH-3", "C-104", "RFI 12", "$12,500.00", "[source:", "ENTITIES.md", "license")),
      "the tool tells the AI the reference formats, sources, intel reports and privacy rule")
p.stdin.close()
p.wait(timeout=10)

shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if ok else 1)
