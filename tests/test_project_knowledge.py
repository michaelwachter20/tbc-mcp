# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Tests the knowledge base without TBC: the project knowledge shared with Civil 3D MCP and Project Analyzer
(mcp_server/projects.py) and the general-knowledge rules (duplicate checks, lessons surfacing by command).
Everything runs in a temporary folder; the real knowledge bases are never touched.
Usage: python test_project_knowledge.py
"""
import json, os, shutil, subprocess, sys, tempfile

here = os.path.dirname(os.path.abspath(__file__))
server = os.path.join(here, "..", "mcp_server", "tbc_mcp_server.py")
work = tempfile.mkdtemp(prefix="tbc_mcp_kb_test_")
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

# --- 9. the server, over stdio, without TBC -------------------------------------------------------------------
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
p.stdin.close()
p.wait(timeout=10)

shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if ok else 1)
