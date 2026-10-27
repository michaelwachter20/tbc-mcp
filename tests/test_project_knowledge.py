# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Tests the project knowledge without TBC: the suite's project database (mcp_server/projects.py) and the shared good
practices (mcp_server/practices.py), following project-analyzer's docs/suite-knowledge.md.

Needs TBC
    No. Everything runs in a temporary folder (CIVIL3D_KNOWLEDGE_DIR and TBC_MCP_KNOWLEDGE_DIR point into it) on a
    copy of tests/fixtures/fixture.db, the suite's made-up test job; the real knowledge bases are never touched.

What it checks
    - the shipped schema (mcp_server/project-db.sql) and fixtures are the same as project-analyzer's, when that
      repository is next to this one (skipped otherwise)
    - finding the job of the open .vce: source_root and folders rows, deepest folder wins, across databases
    - every action of tbc_project_notes: list, overview, search, file, entity, timeline, locate, link, unlink, add,
      update, remove, files, read; ownership (TBC changes only its own facts and folders), fact-N ids, supersedes,
      retired facts, privacy, reference-format hints, a database written by a newer tool (read only)
    - creating a database for a new job, and importing an old <slug>.json notes file once
    - the once-per-job overview attached to the first result of a session
    - tbc_practices on practices.json: list, search, add, update, remove, ownership, unknown fields, file format
    - the server over stdio: instructions, tool list and descriptions, calls without TBC

How to run
    py -3.12 tests\\test_project_knowledge.py
PASS/FAIL per check; exit code 0 when all pass, else 1.
"""
import hashlib, json, os, shutil, site, sqlite3, subprocess, sys, tempfile

here = os.path.dirname(os.path.abspath(__file__))
repo = os.path.normpath(os.path.join(here, ".."))
server = os.path.join(repo, "mcp_server", "tbc_mcp_server.py")
fixtures = os.path.join(here, "fixtures")
analyzer = os.path.normpath(os.path.join(repo, "..", "project-analyzer"))
if not os.path.isdir(analyzer):  # this repository may be a worktree: look next to the main checkout too
    analyzer = os.path.join(os.path.expanduser("~"), "Documents", "GitHub", "project-analyzer")
work = tempfile.mkdtemp(prefix="tbc_mcp_kb_test_")
# Keep this Python's user site-packages (where pip --user puts zstandard) for the server started below: on Windows
# it is found through APPDATA, which is redirected next
os.environ.setdefault("PYTHONUSERBASE", site.getuserbase())
# The test folder lives in %TEMP%, which the privacy check refuses to link: point the per-user folders elsewhere
for var in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
    os.environ[var] = os.path.join(work, "private", var)
    os.makedirs(os.environ[var])
os.environ.pop("TBC_MCP_USER_DIR", None)
shared = os.path.join(work, "shared")
general = os.path.join(work, "general")
os.environ["CIVIL3D_KNOWLEDGE_DIR"] = shared
os.environ["TBC_MCP_KNOWLEDGE_DIR"] = general
sys.path.insert(0, os.path.join(repo, "mcp_server"))
import knowledge as K  # noqa: E402
import projects as P  # noqa: E402
import practices as PR  # noqa: E402

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


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def sql(path, query, args=()):
    db = sqlite3.connect(path)
    try:
        rows = db.execute(query, args).fetchall()
        db.commit()
        return rows
    finally:
        db.close()


# --- 0. the shipped schema and fixtures are project-analyzer's -------------------------------------------------
for ours, theirs in (("mcp_server/project-db.sql", "schema/project-db.sql"), ("tests/fixtures/fixture.db", "schema/fixture.db"),
                     ("tests/fixtures/fixture-practices.json", "schema/fixture-practices.json")):
    src = os.path.join(analyzer, *theirs.split("/"))
    if os.path.isfile(src):
        check(sha(os.path.join(repo, *ours.split("/"))) == sha(src), "%s is the same as project-analyzer's %s" % (ours, theirs))
    else:
        print("SKIP %s: project-analyzer's %s isn't on this computer" % (ours, theirs))

# --- the made-up job: a copy of the fixture, its folders moved into the temp folder ----------------------------
job = os.path.join(work, "jobs", "Elm Street")
for sub in ("TBC", os.path.join("TBC", "Phase 2"), "Drawings", "Survey"):
    os.makedirs(os.path.join(job, sub))
for rel in (("Drawings", "Topo.dwg"), ("Survey", "CP.job")):
    with open(os.path.join(job, *rel), "w") as f:
        f.write("x")
projects_dir = os.path.join(shared, "projects")
os.makedirs(projects_dir)
elm = os.path.join(projects_dir, "elm-street-drainage.db")
shutil.copy(os.path.join(fixtures, "fixture.db"), elm)
sql(elm, "UPDATE meta SET value = ? WHERE key = 'source_root'", (job,))
sql(elm, "UPDATE folders SET path = replace(path, 'C:\\Jobs\\Elm Street', ?)", (job,))
shutil.copy(os.path.join(fixtures, "fixture-practices.json"), os.path.join(shared, "practices.json"))
vce = os.path.join(job, "TBC", "Elm.vce")
deep_vce = os.path.join(job, "TBC", "Phase 2", "Phase 2.vce")
survey_vce = os.path.join(job, "Survey", "Field.vce")

# --- 1. which job ------------------------------------------------------------------------------------------------
check(P.slug("Elm Street Drainage") == "elm-street-drainage" and P.slug("  --A/B 1--  ") == "a-b-1", "slug matches the contract")
check((P.project_for_path(vce) or {}).get("name") == "Elm Street Drainage", "the open .vce in a linked folder matches the job")
check((P.project_for_path(survey_vce.upper()) or {}).get("name") == "Elm Street Drainage",
      "a .vce under source_root matches too (any case)")
check(P.project_for_path(os.path.join(work, "elsewhere", "x.vce")) is None, "a .vce outside every job folder matches nothing")
check(P.project_for_path("Untitled") is None, "an unsaved project matches nothing")
stamp = P._index[elm][0]
P.project_for_path(vce)
check(P._index[elm][0] == stamp, "the job index is cached by the database's file stamp")

# --- 2. read actions on the fixture ----------------------------------------------------------------------------
P.list_notes(None, vce)  # the first open switches the copy to WAL; reads from here on must not change it
before = sha(elm)
listed = P.list_notes(None, vce)
ids = {f["id"]: f["by"] for f in listed["facts"]}
check(ids == {"fact-1": "project-analyzer", "fact-3": "project-analyzer", "fact-4": "civil3d", "fact-5": "tbc"},
      "list: current facts with their tool; superseded fact-2 and retired fact-6 hidden: %s" % ids)
check([f["by"] for f in listed["folders"]] == ["project-analyzer", "civil3d", "tbc"], "list: source_root and folders, with their tool")

o = P.overview(None, vce)
check(o["project"] == "Elm Street Drainage" and o["source_root"] == job and o["copy_status"].startswith("copy of"), "overview: meta")
check(o["files_by_status"] == {"done": 8, "duplicate": 1, "failed": 1}, "overview: files by status %s" % o["files_by_status"])
check(sorted(f["id"] for f in o["key_facts"]) == ["fact-1", "fact-3", "fact-5"], "overview: key facts (not superseded or retired)")
check(len(o["newest_facts"]) == 4 and [q["id"] for q in o["open_questions"]] == ["q-1"] and [r["id"] for r in o["rules"]] == ["rule-1"],
      "overview: newest facts, open questions only, rules")
check([c["id"] for c in o["checks_high"]] == ["check-1"] and o["missing_files"] == 1, "overview: high checks only, missing files")
check([p["name"] for p in o["people"]][:2] == ["John Smith", "Robin Lee"] and o["people"][0]["aliases"] == ["J. Smith"], "overview: people")
check([p["id"] for p in o["practices"]] == ["practice-1", "practice-2"] and "COPIED FOLDER" in o.get("copied_folder", ""),
      "overview: practices and the copied-folder hint")

s = P.search("MH-3", None, vce)
paths = [h["path"] for h in s["documents"]]
check({"Documents\\specs.pdf", "Drawings\\C-104.dwg", "Documents\\minutes.docx"} <= set(paths), "search: MH-3 in documents %s" % paths)
spec = next(h for h in s["documents"] if h["path"] == "Documents\\specs.pdf")
check(spec["part"] == "p.2" and "MH-3" in spec["snippet"], "search: hit names the page and shows a snippet")
check([f["id"] for f in s["facts"]] == ["fact-1"], "search: facts LIKE every word")
check([h["path"] for h in P.search("12+50", None, vce)["documents"]] == ["Drawings\\C-104.dwg"], "search: a station is a phrase")
check(P.search("contractor acme", None, vce)["facts"][0]["id"] == "fact-3", "search: every word must be in a fact")
check(raises(lambda: P.search("  ", None, vce), "query is required"), "search: needs words")

f = P.file_info("documents/SPECS.PDF", None, vce)
check(f["file"]["id"] == "0000000000000002" and f["text"].startswith("## p.1") and "## p.3" in f["text"], "file: by path (any case), text with its pages")
check([x["id"] for x in f["facts"]] == ["fact-3"] and f["absolute"] == os.path.join(job, "Documents", "specs.pdf"), "file: facts citing it, absolute path")
f = P.file_info("0000000000000003", None, vce)
check(len(f["refs_from"]) == 2 and f["props"].get("title_block.sheet") == "C-104", "file: by id, references from it and its details")
check(P.file_info("minutes.docx", None, vce)["summary"]["summary"], "file: by name, with its summary")
f = P.file_info("Documents\\minutes copy.docx", None, vce)
check(f["file"]["status"] == "duplicate" and "MH-3" in f.get("text", "") and "text_from" in f, "file: a duplicate shows the text of its original")
check(P.file_info("0000000000000003", None, vce, max_chars=20).get("truncated"), "file: text cut at max_chars")
check(raises(lambda: P.file_info("specs", None, vce), "did you mean"), "file: an unknown name suggests matches")

e = P.entity("j. smith", None, vce)
check(e["found"] and e["entity"]["name"] == "John Smith", "entity: found by alias, any case")
check([x["path"] for x in e["files"]] == ["Documents\\minutes.docx", "Email\\RFI 12.msg"] and len(e["events"]) == 2,
      "entity: its files and events")
check([x["id"] for x in e["stories"]] == ["story-1"] and len(e["stories"][0]["steps"]) == 2, "entity: stories naming it, with steps")
e = P.entity("MH-3", None, vce)
check(e["found"] and [x["id"] for x in e["facts"]] == ["fact-1"], "entity: facts whose topics name it")
e = P.entity("Nobody Here", None, vce)
check(e["found"] is False and "similar" in e, "entity: unknown name says so")

t = P.timeline(None, vce)
dates = [x["date"] for x in t["events"]]
check(dates == sorted(dates) and len(dates) == 5 and any(x.get("fact") == "fact-1" for x in t["events"]), "timeline: events and dated facts in order")
check([x["date"] for x in P.timeline(None, vce, "2026-10", "2026-10-05")["events"]] == ["2026-10-03", "2026-10-03", "2026-10-05"],
      "timeline: between two dates, both included")
check(raises(lambda: P.timeline(None, vce, "10/3/26"), "yyyy"), "timeline: dates in ISO form only")

r = P.locate("p:/jobs/1234 elm st/cad/TOPO.DWG", None, vce)
check(r["status"] == "found" and r["source"] == "refs" and r["absolute"] == os.path.join(job, "Drawings", "Topo.dwg") and r["exists"]
      and r["referenced_by"] == ["Drawings\\C-104.dwg"], "locate: a found reference, with absolute path (case and slashes don't matter)")
r = P.locate("file:///P:/Jobs/1234%20Elm%20St/Images/aerial.jpg", None, vce)
check(r["status"] == "missing" and r["expected_at"]["absolute"] == os.path.join(job, "Images", "aerial.jpg") and "ask the user" in r["hint"].lower(),
      "locate: a missing reference says where it belongs (file: URLs work)")
r = P.locate("\"P:\\JOBS\\1234 Elm St\\Survey\\CP.job\"", None, vce)
check(r["status"] == "translated" and r["source"] == "reference_roots" and r["exists"] and r["relative"] == "Survey\\CP.job",
      "locate: a path not in refs is translated through reference_roots")
r = P.locate("P:\\Jobs\\1234 Elm St\\Survey\\Gone.job", None, vce)
check(r["status"] == "translated, not found" and not r["exists"], "locate: a translated path with no file says so")
r = P.locate("Q:\\Other Job\\x.job", None, vce)
check(r["status"] == "not known" and r["source"] is None and "ask the user where the original" in r["hint"], "locate: never guesses")
check(raises(lambda: P.locate("", None, vce), "path is required"), "locate: needs a path")
check(sha(elm) == before and not os.path.exists(elm + "-journal"), "read actions never write the database")

# --- 3. facts: TBC writes only its own --------------------------------------------------------------------------
r = P.add_note("Survey control is on layer CTRL\nat 12+50", None, vce, topics=["control"], date="2026-10-12")
fact = r["fact"]
check(r["action"] == "added" and fact["id"] == "fact-7" and fact["by"] == "tbc", "add: fact-7 (after the retired fact-6), tool tbc")
check(fact["fact"] == "Survey control is on layer CTRL at 12+50" and fact["topics"] == ["control"] and fact["date"] == "2026-10-12",
      "add: one line, with topics and date")
check(fact["sources"] == [{"file": "tbc:Elm.vce", "path": "Elm.vce"}] and fact["added"].endswith("Z") and len(fact["added"]) == 24,
      "add: source is the open TBC project (file name only inside the user profile), toISOString time")
r = P.add_note("the tbc project uses the nad83 illinois east zone.", None, vce, source="user")
check(r["action"] == "source added" and r["fact"]["id"] == "fact-5" and len(r["fact"]["sources"]) == 2,
      "add: the same text as TBC's own fact adds the source instead of a duplicate")
check(P.add_note("The TBC project uses the NAD83 Illinois East zone.", None, vce, source="user")["action"] == "unchanged",
      "add: ...and a source it already has changes nothing")
r = P.add_note("STORM PIPES IN THIS DRAWING ARE ON LAYER C-STRM.", None, vce)
check(r["action"] == "unchanged" and r["fact"]["id"] == "fact-4" and r["fact"]["by"] == "civil3d", "add: another tool's fact is left as it is")
check(raises(lambda: P.update_note("fact-4", "x", None, vce), "civil 3d mcp") and raises(lambda: P.remove_note("fact-1", None, vce), "project analyzer"),
      "update / remove refuse other tools' facts")
check(raises(lambda: P.update_note("fact-6", "x", None, vce), "removed") and raises(lambda: P.update_note("fact-99", "x", None, vce), "no fact"),
      "update refuses retired and unknown facts")
r = P.update_note("fact-7", "Survey control is on layer CTRL at 12+50.25", None, vce, key=True)
check(r["fact"]["fact"].endswith("12+50.25") and r["fact"].get("key") and r["fact"].get("updated"), "update: own fact, with 'updated'")
r = P.remove_note("fact-7", None, vce)
check(r["fact"].get("retired") and "fact-7" not in [x["id"] for x in P.list_notes(None, vce)["facts"]], "remove: sets retired, hidden from list")
check(sql(elm, "SELECT COUNT(*) FROM facts WHERE id = 'fact-7'")[0][0] == 1, "remove: the row is kept")
r = P.add_note("Storm pipes are on layer C-STRM-NEW in the TBC export", None, vce, supersedes="fact-4")
check(r["fact"]["id"] == "fact-8" and r["fact"]["supersedes"] == "fact-4", "add: ids are never reused; supersedes corrects another tool's fact")
check("fact-4" not in [x["id"] for x in P.list_notes(None, vce)["facts"]], "...and the corrected fact is no longer current")
check(raises(lambda: P.add_note("x", None, vce, supersedes="fact-99"), "no fact"), "supersedes must name a fact")
sql(elm, "INSERT INTO facts(id, fact, tool, added) VALUES ('fact-9', 'Civil 3D wrote this meanwhile', 'civil3d', '2026-10-26T00:00:00.000Z')")
check(P.add_note("Another TBC fact", None, vce)["fact"]["id"] == "fact-10", "fact-N is read in the write transaction (another tool wrote fact-9)")
check(raises(lambda: P.add_note("x", None, vce, date="10/3/26"), "yyyy") and raises(lambda: P.add_note("x", None, vce, topics=[1]), "topics")
      and raises(lambda: P.add_note("x", None, vce, confidence="sure"), "confidence") and raises(lambda: P.add_note("  ", None, vce), "empty"),
      "add checks date, topics, confidence and empty text")
P.add_private("tok3n-abcdef", "the bridge's session token")
check(raises(lambda: P.add_note("token is tok3n-ABCDEF", None, vce), "session token"), "a session token is refused")
check(raises(lambda: P.add_note("see %s\\Documents\\x.vce" % os.path.expanduser("~"), None, vce), "user profile"), "a user-profile path is refused")
loose = "Manhole 3 rim checked on 10/3/26 at Sta. 1250 (sheet C104), CO #4 was 12.5k"
hints = P.format_hints(loose)
check(P.add_note(loose, None, vce).get("format_hints") and len(hints) == 6, "facts in other formats are saved, with hints: %s" % hints)
check("format_hints" not in P.add_note("MH-3 rim checked 2026-10-03 at 12+50 (C-104), RFI 12, $12,500.00", None, vce),
      "facts in the suite's formats get no hints")
other = P.add_note("Fact for a named job", "Elm Street Drainage", deep_vce.replace("Elm Street", "Other"))
check(other["fact"]["sources"] == [{"file": "user", "path": "said by the user"}], "a named job not open in TBC records the user as source")
newer = os.path.join(projects_dir, "newer-job.db")
shutil.copy(os.path.join(fixtures, "fixture.db"), newer)
sql(newer, "UPDATE meta SET value = '2' WHERE key = 'schema_version'")
sql(newer, "UPDATE meta SET value = 'Newer Job' WHERE key = 'project_name'")
check(P.overview("Newer Job", None).get("read_only") and raises(lambda: P.add_note("x", "Newer Job", None), "newer version"),
      "a database of a newer schema is read, never written")

# --- 4. link / unlink, a new job's database ---------------------------------------------------------------------
r = P.link("Phase Two", None, deep_vce)
phase = os.path.join(projects_dir, "phase-two.db")
meta = dict(sql(phase, "SELECT key, value FROM meta"))
check(r["action"] == "created" and os.path.isfile(phase) and r["folders"] == [{"path": os.path.dirname(deep_vce), "by": "tbc"}],
      "link creates the job's database with the open .vce's folder (tool tbc)")
check(meta.get("schema_version") == "1" and len(meta.get("project_id", "")) == 12 and meta.get("project_name") == "Phase Two"
      and meta.get("created", "").endswith("Z"), "a new database has schema_version, project_id, project_name and created")
check(sql(phase, "PRAGMA journal_mode")[0][0] == "wal" and os.path.isdir(os.path.join(projects_dir, "phase-two")),
      "...in WAL mode, with its files folder")
check(P.project_for_path(deep_vce)["name"] == "Phase Two", "deepest folder wins across databases")
check(P.link("Phase Two", os.path.dirname(deep_vce).upper() + "\\", deep_vce)["action"] == "unchanged", "the same folder isn't linked twice")
check(P.link("Elm Street Drainage", os.path.join(job, "drawings"), None)["action"] == "unchanged", "a folder another tool linked changes nothing")
check(P.link("Elm Street Drainage", job, None)["action"] == "unchanged", "the analysed folder (source_root) counts as linked")
check(raises(lambda: P.unlink("Elm Street Drainage", os.path.join(job, "Drawings")), "civil 3d mcp"), "a folder Civil 3D linked can't be unlinked")
check(P.unlink("Phase Two", os.path.dirname(deep_vce))["folders"] == [], "unlink drops TBC's own folder, the job stays")
check(P.project_for_path(deep_vce)["name"] == "Elm Street Drainage", "after unlink the outer job matches again")
check(raises(lambda: P.link("Phase Two", os.path.join(os.environ["LOCALAPPDATA"], "TBC-MCP"), None), "private"), "a per-user folder can't be linked")
check(raises(lambda: P.add_note("x", None, os.path.join(work, "nowhere", "a.vce")), "action=link"), "an unknown folder asks to link")
nomatch = P.list_notes(None, os.path.join(work, "nowhere", "a.vce"))
check(nomatch["project"] is None and "Elm Street Drainage" in [j["name"] for j in nomatch["known_projects"]], "list without a match lists the known jobs")

# --- 5. an old <slug>.json notes file is imported once ----------------------------------------------------------
legacy_dir = os.path.join(work, "jobs", "Three Tools")
os.makedirs(os.path.join(legacy_dir, "TBC"))
legacy = {"name": "Three Tools", "folders": [legacy_dir], "civil3d_view": {"zoom": 1.5},
          "notes": [{"id": "note-1", "note": "Point group Hide holds the shots\nbeyond the right-of-way.", "added": "2026-10-20T10:00:00.000Z"},
                    {"id": "note-2", "note": "Müller Surveying set the control", "added": "2026-10-25T21:42:47.123Z", "source": "project-analyzer"},
                    {"id": "note-3", "note": "The TBC project uses US feet.", "added": "2026-10-21T08:00:00.000Z",
                     "updated": "2026-10-22T08:00:00.000Z", "source": "tbc"},
                    {"id": "note-4", "note": "  "}, "not a note"]}
legacy_path = os.path.join(projects_dir, "three-tools.json")
with open(legacy_path, "w", encoding="utf-8-sig") as f:  # as Civil 3D MCP wrote it, with a BOM
    f.write(json.dumps(legacy, indent=2, ensure_ascii=False) + "\n")
three_vce = os.path.join(legacy_dir, "TBC", "Three.vce")
check((P.project_for_path(three_vce) or {}).get("name") == "Three Tools" and not os.path.exists(legacy_path[:-5] + ".db"),
      "a job known only from its JSON file is found (without creating anything)")
listed = P.list_notes(None, three_vce)
three_db = legacy_path[:-5] + ".db"
facts = {r[0]: r[1:] for r in sql(three_db, "SELECT fact, tool, sources, origin, added, updated FROM facts")}
check(os.path.isfile(three_db) and not os.path.exists(legacy_path) and os.path.isfile(legacy_path + ".imported"),
      "first open creates <slug>.db and renames the JSON file to .json.imported")
check(facts.get("Point group Hide holds the shots beyond the right-of-way.", [None])[0] == "civil3d"
      and facts.get("Müller Surveying set the control", [None])[0] == "project-analyzer"
      and facts.get("The TBC project uses US feet.", [None])[0] == "tbc" and len(facts) == 3,
      "each note is a fact owned by its source (none = civil3d); empty notes skipped")
tbc_note = facts["The TBC project uses US feet."]
check(json.loads(tbc_note[1]) == [{"file": "user", "path": "project note"}] and json.loads(tbc_note[2]) == {"note_id": "note-3"}
      and tbc_note[3] == "2026-10-21T08:00:00.000Z" and tbc_note[4] == "2026-10-22T08:00:00.000Z",
      "sources, origin note_id and the times are kept")
check(sql(three_db, "SELECT path, tool FROM folders") == [(legacy_dir, "civil3d")] and
      dict(sql(three_db, "SELECT key, value FROM meta")).get("project_name") == "Three Tools", "folders (civil3d) and the name are imported")
check(sorted(f["id"] for f in listed["facts"]) == ["fact-1", "fact-2", "fact-3"], "the imported facts are listed")
os.rename(legacy_path + ".imported", legacy_path)  # as if the rename had failed (file in use): no second import
P.list_notes("Three Tools", None)
check(sql(three_db, "SELECT COUNT(*) FROM facts")[0][0] == 3 and not os.path.exists(legacy_path)
      and os.path.isfile(legacy_path + ".imported"), "a second open never imports again, only renames")
check(P.update_note("fact-3", "The TBC project uses US survey feet.", "Three Tools", None)["action"] == "updated"
      and raises(lambda: P.remove_note("fact-1", "Three Tools", None), "civil 3d mcp"), "imported TBC notes are TBC's own, others' are not")
with open(os.path.join(projects_dir, "broken-job.json"), "w", encoding="utf-8") as f:
    f.write('{"name": "Broken Job", "notes": [')
P.link("Broken Job", os.path.join(work, "jobs", "Broken"), None)
check(open(os.path.join(projects_dir, "broken-job.json"), encoding="utf-8").read() == '{"name": "Broken Job", "notes": ['
      and os.path.isfile(os.path.join(projects_dir, "broken-job.db")), "a JSON file that doesn't parse is left alone")
link_legacy = {"name": "Linked Later", "folders": [os.path.join(work, "jobs", "Later", "CAD")],
               "notes": [{"id": "note-1", "note": "Imported when TBC links the job", "added": "2026-10-20T10:00:00.000Z"}]}
with open(os.path.join(projects_dir, "linked-later.json"), "w", encoding="utf-8") as f:
    json.dump(link_legacy, f)
r = P.link("linked later", os.path.join(work, "jobs", "Later", "TBC"), None)
check(r["action"] == "linked" and len(r["folders"]) == 2 and
      sql(os.path.join(projects_dir, "linked-later.db"), "SELECT COUNT(*) FROM facts")[0][0] == 1, "linking a JSON-only job imports it first")

# --- 6. the job's files folder ------------------------------------------------------------------------------------
files = os.path.join(projects_dir, "elm-street-drainage")
os.makedirs(os.path.join(files, "Standards"), exist_ok=True)
with open(os.path.join(files, "Standards", "layers.md"), "w", encoding="utf-8") as f:
    f.write("# Layer standard\n\nC-STRM for storm pipes.\n")
with open(os.path.join(files, "photo.jpg"), "wb") as f:
    f.write(b"\xff\xd8\x00\x00binary")
r = P.project_files(None, vce)
check([x["path"] for x in r["files"]] == ["photo.jpg", os.path.join("Standards", "layers.md")], "files lists the user's files for the job")
check(P.read_file("Standards/layers.md", None, vce)["text"].startswith("# Layer standard"), "read returns a text file")
check(P.read_file("Standards\\layers.md", None, vce, max_chars=5).get("truncated"), "long files are cut at max_chars")
check(raises(lambda: P.read_file("..\\elm-street-drainage.db", None, vce), "inside"), "paths outside the files folder are refused")
check(raises(lambda: P.read_file("photo.jpg", None, vce), "isn't a text file"), "binary files are refused")

# --- 7. the overview reaches the AI once per job -----------------------------------------------------------------
P.reset_announcements()
first = P.notes_once(vce) or {}
check(first.get("project") == "Elm Street Drainage" and [c["id"] for c in first.get("checks_high", [])] == ["check-1"]
      and first.get("missing_files") == 1, "the first result carries the job's high checks and missing-file count")
check(sorted(f["id"] for f in first.get("key_facts", [])) == ["fact-1", "fact-3", "fact-5"] and "fact-5" in [f["id"] for f in first.get("tbc_facts", [])],
      "...its key facts and TBC's own facts")
check("12+50" in first.get("hint", "") and "COPIED FOLDER" in first.get("copied_folder", ""), "...with the reference formats and the copy hint")
check(P.notes_once(vce) is None, "...and only once per server run")
check(P.notes_once(os.path.join(work, "nowhere", "a.vce")) is None, "no job, no overview")

# --- 8. legacy Civil 3D MCP folder is moved, as Civil 3D MCP itself does -------------------------------------
docs = os.path.join(work, "Documents")
os.makedirs(os.path.join(docs, "Civil3DMcp", "projects"))
check(P.migrate_legacy_folder(docs) and os.path.isdir(os.path.join(docs, "Civil3DMcp-KnowledgeBase", "projects")), "Documents\\Civil3DMcp moved to Civil3DMcp-KnowledgeBase")
check(P.migrate_legacy_folder(docs) is None, "migration runs only once")

# --- 9. good practices (practices.json) ---------------------------------------------------------------------------
practices_path = os.path.join(shared, "practices.json")
with open(practices_path, encoding="utf-8") as f:
    data = json.load(f)
data["practices"][0]["civil3d_extra"] = {"keep": [1, 2.5, None]}
data["note_for_people"] = "kept"
with open(practices_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
check([p["id"] for p in PR.list_practices()["practices"]] == ["practice-1", "practice-2"], "list: the practices")
check([p["id"] for p in PR.search("slope")["practices"]] == ["practice-1"], "search: by words")
r = PR.add("Survey control points are set\nevery 500 ft.", ["survey", "Control"])
check(r["action"] == "added" and r["practice"]["id"] == "practice-3" and r["practice"]["source"] == "tbc"
      and r["practice"]["practice"] == "Survey control points are set every 500 ft." and r["practice"]["topics"] == ["survey", "control"],
      "add: practice-3, source tbc, one line, topics")
check(PR.add("storm pipe minimum slope is 0.5%.")["action"] == "unchanged", "add: no duplicate (any case)")
check(raises(lambda: PR.update("practice-1", "x"), "civil 3d mcp") and raises(lambda: PR.remove("practice-1"), "civil 3d mcp"),
      "update / remove refuse another tool's practice")
check(PR.update("practice-2", topics=["labels", "structures"])["practice"]["topics"] == ["labels", "structures"], "update: own practice's topics")
r = PR.remove("practice-2")
check(r["practice"].get("retired") and [p["id"] for p in PR.list_practices()["practices"]] == ["practice-1", "practice-3"],
      "remove: retired and hidden")
check(len(PR.list_practices(True)["practices"]) == 3 and PR.add("Name surfaces EG and FG.")["practice"]["id"] == "practice-4",
      "retired practices are kept and their ids never reused")
with open(practices_path, "rb") as f:
    raw = f.read()
data = json.loads(raw.decode("utf-8"))
check(data["practices"][0]["civil3d_extra"] == {"keep": [1, 2.5, None]} and data["note_for_people"] == "kept", "unknown fields are kept")
check(not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw and raw.endswith(b"}\n") and b'\n  "practices": [' in raw,
      "written as UTF-8 without BOM, LF, 2-space indent")
check(not [n for n in os.listdir(shared) if n.endswith(".tmp")], "no temp files left behind")
check(raises(lambda: PR.add("On Elm Street Drainage use 1% slopes"), "tbc_project_notes"), "a practice naming a job is refused")
check(raises(lambda: PR.add("token tok3n-abcdef"), "private"), "a practice with private data is refused")
text = PR.practices_text()
check("[practice-1] Storm pipe minimum slope is 0.5%." in text and "practice-2" not in text, "practices_text lists the current practices")
with open(practices_path, "w", encoding="utf-8") as f:
    f.write('{"practices": [')
check(raises(lambda: PR.add("x y z"), "can't be read") and open(practices_path, encoding="utf-8").read() == '{"practices": ['
      and PR.current() == [] and PR.practices_text() == "", "a file that doesn't parse is never rewritten (and shows nothing)")
with open(practices_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

# --- 10. the server, over stdio, without TBC ------------------------------------------------------------------
K.add_pref("Use numeric point IDs for new points")
env = dict(os.environ, TBC_MCP_INFO=os.path.join(work, "no_bridge.json"), TBC_MCP_EXIT_WITH_TBC="0", PYTHONDONTWRITEBYTECODE="1")
p = subprocess.Popen([sys.executable, server], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     env=env, text=True, encoding="utf-8")


def rpc(i, method, params):
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params}) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())["result"]


def call(i, name, args):
    r = rpc(i, "tools/call", {"name": name, "arguments": args})
    text = r["content"][0]["text"]
    return r["isError"], (text if r["isError"] else json.loads(text))


init = rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
ins = init["instructions"]
check(init["serverInfo"]["version"] == "0.4.0", "server version 0.4.0")
check("THREE KINDS OF KNOWLEDGE" in ins and "tbc_practices" in ins and "tbc_project_notes" in ins, "instructions explain the three kinds of knowledge")
check("Use numeric point IDs for new points" in ins and "GOOD PRACTICES" in ins and "[practice-1] Storm pipe minimum slope" in ins,
      "instructions carry the user's preferences and the suite's practices")
tools = {t["name"]: t for t in rpc(2, "tools/list", {})["tools"]}
check("tbc_project_notes" in tools and "tbc_practices" in tools, "tbc_project_notes and tbc_practices are listed (%d tools)" % len(tools))
check(set(tools["tbc_project_notes"]["inputSchema"]["properties"]["action"]["enum"]) ==
      {"list", "overview", "search", "file", "entity", "timeline", "locate", "link", "unlink", "add", "update", "remove", "files", "read"},
      "tbc_project_notes offers every action")
desc = tools["tbc_project_notes"]["description"]
check(all(s in desc for s in ("12+50", "MH-3", "C-104", "RFI 12", "$12,500.00", "license", "supersedes", "tbc_memory", "tbc_practices")),
      "the tool tells the AI the reference formats, privacy, supersedes and where other knowledge goes")
check(all(s in desc for s in ("locate", "never guess", "BEFORE telling the user", "overview", "search", "entity", "timeline")),
      "the tool says when to use locate and the read actions")
err, r = call(3, "tbc_project_notes", {"action": "overview", "project": "Elm Street Drainage"})
check(not err and r["project"] == "Elm Street Drainage" and r["checks_high"], "overview of a named job works without TBC")
err, r = call(4, "tbc_project_notes", {"action": "search", "project": "Elm Street Drainage", "query": "culvert 36"})
check(not err and r["documents"], "search over MCP%s" % ("" if not err else ": " + r))
err, r = call(5, "tbc_project_notes", {"action": "entity", "project": "Elm Street Drainage", "name": "RFI 12"})
check(not err and r["found"], "entity over MCP")
err, r = call(6, "tbc_project_notes", {"action": "add", "note": "x"})
check(err and "action=link" in r, "no TBC and no project name -> asks for a name to link")
err, r = call(7, "tbc_project_notes", {"action": "locate", "project": "Elm Street Drainage", "path": "P:\\Jobs\\1234 Elm St\\CAD\\Topo.dwg"})
check(not err and r["absolute"] == os.path.join(job, "Drawings", "Topo.dwg"), "locate over MCP")
err, r = call(8, "tbc_project_notes", {"action": "add", "project": "Elm Street Drainage", "note": "Added over MCP", "topics": ["mcp"]})
check(not err and r["fact"]["by"] == "tbc" and r["fact"]["sources"][0]["file"] == "user", "add over MCP")
err, r = call(9, "tbc_project_notes", {"action": "nonsense"})
check(err and "overview" in r, "an unknown action lists the actions")
err, r = call(10, "tbc_practices", {"action": "search", "query": "slope"})
check(not err and r["practices"][0]["id"] == "practice-1", "tbc_practices over MCP")
err, r = call(11, "tbc_memory", {"action": "add", "text": "Elm Street Drainage uses US feet", "topic": "units"})
check(err and "tbc_project_notes action=add" in r, "tbc_memory refuses job data and points to the project notes")
p.stdin.close()
p.wait(timeout=10)

shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if ok else 1)
