# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Tests the project knowledge without TBC: the suite's project database (mcp_server/projects.py) and the shared good
practices (mcp_server/practices.py), following project-analyzer's docs/suite-knowledge.md.

Needs TBC
    No. Everything runs in a temporary folder (PROJECT_KNOWLEDGE_DIR and TBC_MCP_KNOWLEDGE_DIR point into it) on a
    copy of tests/fixtures/fixture.db, the suite's made-up test job; the real knowledge bases are never touched.

What it checks
    - the shipped schema (mcp_server/project-db.sql) and fixtures have the SHA-256 recorded below (always), and are
      the same as project-analyzer's when that repository is next to this one (skipped otherwise)
    - finding the job of the open .vce: source_root and folders rows, deepest folder wins, across databases
    - every action of tbc_project_notes: list, overview, search, file, entity, timeline, locate, latest, checks,
      changes, link, unlink, add, update, remove, files, read; ownership (TBC changes only its own facts and folders),
      fact-N ids, supersedes, retired facts, privacy, reference-format hints, a database written by a newer tool
      (read only)
    - creating a database for a new job, and importing an old <slug>.json notes file once (on the first write)
    - opening: reads open read only and never change the file; a writable open adds the schema's indexes; a busy
      database gives a friendly error; a damaged one says how to restore a backup and is listed with a note; TBC's
      daily backup of a database it looks after alone, 3 kept
    - User Knowledge with long paths and unreadable files; search, read and file without the zstandard package
    - TBC MCP installed alone (an empty shared folder): every action answers
    - knowledge files: lock files (a dead holder's taken over), concurrent lessons from threads and processes, a bad
      lessons.jsonl line, temp-file sweep, .bak1..3 of preferences and practices
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
os.environ["PROJECT_KNOWLEDGE_DIR"] = shared
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


def sha(path, text=False):
    """SHA-256 of a file; text=True ignores CRLF vs LF (a checkout may convert line endings)."""
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha256(data.replace(b"\r\n", b"\n") if text else data).hexdigest()


def sql(path, query, args=()):
    db = sqlite3.connect(path)
    try:
        rows = db.execute(query, args).fetchall()
        db.commit()
        return rows
    finally:
        db.close()


# --- 0. the shipped schema and fixtures are project-analyzer's -------------------------------------------------
# The contract copies' SHA-256 as project-analyzer's schema/sync_copies.py prints them (CRLF read as LF for text), so
# drift is caught even where that repository isn't checked out. Update them with the copies.
CONTRACT_SHA = {"mcp_server/project-db.sql": "44c31481779f67dc3187f4f66e3a81f48c40b1c1c0452505456550473a218abb",
                "tests/fixtures/fixture.db": "451ee3ea467c7bcdc5ebad3b0866ce0b6597ea5e102582a7831ae2e9cfbf8a0b",
                "tests/fixtures/fixture-practices.json": "f2021ce1b963686cec2270567e8050e25bdb814c6cff76412c2f8338dbcdafa6"}
for ours, expected in CONTRACT_SHA.items():
    check(sha(os.path.join(repo, *ours.split("/")), not ours.endswith(".db")) == expected, "%s has the recorded SHA-256" % ours)
for ours, theirs in (("mcp_server/project-db.sql", "schema/project-db.sql"), ("tests/fixtures/fixture.db", "schema/fixture.db"),
                     ("tests/fixtures/fixture-practices.json", "schema/fixture-practices.json")):
    src = os.path.join(analyzer, *theirs.split("/"))
    if os.path.isfile(src):
        text = not ours.endswith(".db")
        check(sha(os.path.join(repo, *ours.split("/")), text) == sha(src, text), "%s is the same as project-analyzer's %s" % (ours, theirs))
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
# Reads open the database read only: the copy (journal mode delete, as the fixture is) must not change at all
before, before_mtime = sha(elm), os.path.getmtime(elm)
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
for read in (lambda: P.latest("C-104", None, vce), lambda: P.checks(None, vce), lambda: P.changes(None, vce, since="2026"),
             lambda: P.project_files(None, vce), lambda: P.describe(P.project_for_path(vce))):
    read()
check(sha(elm) == before and os.path.getmtime(elm) == before_mtime and not any(
      os.path.exists(elm + x) for x in ("-journal", "-wal", "-shm")), "read actions never write the database (bytes, time, no journal)")
check(sql(elm, "PRAGMA journal_mode")[0][0] == "delete", "...nor switch its journal to WAL (only a write does)")

# A job with more than one folder (contract: "More than one folder per job"): an extra folder's files are stored as
# "<job folder: NAME>\\..."; TBC finds the job from a project in that folder and gives each file's real place.
survey = os.path.join(work, "survey drive", "Survey")
os.makedirs(os.path.join(survey, "TBC"))
open(os.path.join(survey, "CP.job"), "w").close()
sql(elm, "INSERT INTO meta(key, value) VALUES ('job_folders', ?)", (json.dumps([{"name": "Survey", "path": survey}]),))
sql(elm, "INSERT INTO files(id, root_id, parent_id, depth, path, name, ext, kind, status) VALUES "
         "('5555555555555555', '5555555555555555', NULL, 0, '<job folder: Survey>\\CP.job', 'CP.job', '.job', 'survey', 'done')")
sql(elm, "INSERT INTO refs(file_id, root_id, kind, raw, normalized, status, target_path) VALUES (?, ?, 'path in text', "
         "'S:\\Survey\\CP.job', 'S:\\Survey\\CP.job', 'found', '<job folder: Survey>\\CP.job')",
    ("5555555555555555", "5555555555555555"))
P.forget_jobs()
check(P.project_for_path(os.path.join(survey, "TBC", "Survey.vce")) and P.project_for_path(os.path.join(
    survey, "TBC", "Survey.vce"))["db"] == elm, "a TBC project in the job's other folder belongs to the job")
with P.opened(P.project_for_path(vce)) as extra_db:
    check(P.on_disk(extra_db, "<job folder: Survey>\\CP.job") == os.path.join(survey, "CP.job"),
          "on_disk: an extra folder's file is in that folder")
f = P.file_info(os.path.join(survey, "CP.job"), None, vce)
check(f.get("absolute") == os.path.join(survey, "CP.job"), "file: found by its real path, with its place on this computer")
r = P.locate("S:\\Survey\\CP.job", None, vce)
check(r["status"] == "found" and r["absolute"] == os.path.join(survey, "CP.job") and r["exists"],
      "locate: a reference into the job's other folder gives that folder's path")
check(any(x.get("job_folder") == "Survey" for x in P.overview(None, vce)["folders"]), "the overview lists the job's other folders")
sql(elm, "DELETE FROM refs WHERE file_id = '5555555555555555'")
sql(elm, "DELETE FROM files WHERE id = '5555555555555555'")
sql(elm, "DELETE FROM meta WHERE key = 'job_folders'")
P.forget_jobs()

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
check(sql(elm, "PRAGMA journal_mode")[0][0] == "wal", "the first write switched the database to WAL")
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
newer_sha = sha(newer)
check(P.overview("Newer Job", None).get("read_only") and raises(lambda: P.add_note("x", "Newer Job", None), "newer version"),
      "a database of a newer schema is read, never written")
check(sha(newer) == newer_sha and not os.path.isdir(os.path.join(projects_dir, "newer-job.backups")),
      "...its file is left exactly as it was (no backup, no index, no journal switch)")

# --- 4. link / unlink, a new job's database ---------------------------------------------------------------------
r = P.link("Phase Two", None, deep_vce)
phase = os.path.join(projects_dir, "phase-two.db")
meta = dict(sql(phase, "SELECT key, value FROM meta"))
check(r["action"] == "created" and os.path.isfile(phase) and r["folders"] == [{"path": os.path.dirname(deep_vce), "by": "tbc"}],
      "link creates the job's database with the open .vce's folder (tool tbc)")
check(meta.get("schema_version") == "1" and len(meta.get("project_id", "")) == 12 and meta.get("project_name") == "Phase Two"
      and meta.get("created", "").endswith("Z"), "a new database has schema_version, project_id, project_name and created")
check(sql(phase, "PRAGMA journal_mode")[0][0] == "wal" and
      os.path.isdir(os.path.join(projects_dir, "phase-two", "User Knowledge")), "...in WAL mode, with its User Knowledge folder")
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
P.forget_jobs()  # a new file in the projects folder: look again now rather than in INDEX_TTL seconds
check((P.project_for_path(three_vce) or {}).get("name") == "Three Tools" and not os.path.exists(legacy_path[:-5] + ".db"),
      "a job known only from its JSON file is found (without creating anything)")
listed = P.list_notes(None, three_vce)
three_db = legacy_path[:-5] + ".db"
check(sorted(f["id"] for f in listed["facts"]) == ["fact-1", "fact-2", "fact-3"] and not os.path.exists(three_db)
      and os.path.isfile(legacy_path) and "old_notes_file" in listed, "a read shows its notes from memory, creating nothing")
check(P.overview(None, three_vce)["project"] == "Three Tools" and P.search("right-of-way", None, three_vce)["facts"]
      and not os.path.exists(three_db), "...for every read action")
check(P.link("Three Tools", legacy_dir, None)["action"] == "unchanged", "the first write (a folder it already has) ...")
facts = {r[0]: r[1:] for r in sql(three_db, "SELECT fact, tool, sources, origin, added, updated FROM facts")}
check(os.path.isfile(three_db) and not os.path.exists(legacy_path) and os.path.isfile(legacy_path + ".imported"),
      "...creates <slug>.db and renames the JSON file to .json.imported")
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
check(sorted(f["id"] for f in P.list_notes(None, three_vce)["facts"]) == ["fact-1", "fact-2", "fact-3"], "the imported facts are listed")
os.rename(legacy_path + ".imported", legacy_path)  # as if the rename had failed (file in use): no second import
P.list_notes("Three Tools", None)
check(os.path.isfile(legacy_path), "a read leaves the JSON file where it is")
P.link("Three Tools", legacy_dir, None)
check(sql(three_db, "SELECT COUNT(*) FROM facts")[0][0] == 3 and not os.path.exists(legacy_path)
      and os.path.isfile(legacy_path + ".imported"), "a second writable open never imports again, only renames")
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

# --- 6. the job's User Knowledge folder (the user's own documents for the job) --------------------------------
import datetime, zipfile  # noqa: E401,E402


def office(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, xml in members.items():
            z.writestr(name, '<?xml version="1.0" encoding="UTF-8"?>' + xml)


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
A = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
     'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
elm_dir = os.path.join(projects_dir, "elm-street-drainage")
uk = os.path.join(elm_dir, "User Knowledge")
for sub in ("Standards", "Guidelines", "Building types"):
    os.makedirs(os.path.join(uk, sub), exist_ok=True)
with open(os.path.join(uk, "Standards", "layers.md"), "w", encoding="utf-8") as f:
    f.write("# Layer standard\n\nC-STRM for storm pipes.\n")
with open(os.path.join(uk, "photo.jpg"), "wb") as f:
    f.write(b"\xff\xd8\x00\x00binary")
# The guide Project Analyzer read (the fixture's <user knowledge>\Guidelines\Proposal guide.pdf): same size and time
guide = os.path.join(uk, "Guidelines", "Proposal guide.pdf")
with open(guide, "wb") as f:
    f.write(b"%PDF-1.4\n" + b"0" * (2048 - 9))
guide_time = datetime.datetime(2026, 10, 20, 12, tzinfo=datetime.timezone.utc).timestamp()
os.utime(guide, (guide_time, guide_time))
office(os.path.join(uk, "Building types", "School requirements.docx"), {"word/document.xml":
       '<w:document %s><w:body><w:p><w:r><w:t>Each classroom wing needs its own storm inlet.</w:t></w:r></w:p>'
       '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Use</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Layer</w:t></w:r></w:p></w:tc>'
       '</w:tr></w:tbl></w:body></w:document>' % W})
office(os.path.join(uk, "Standards", "codes.xlsx"), {
    "xl/workbook.xml": '<workbook %s %s><sheets><sheet name="Codes" sheetId="1" r:id="rId1"/></sheets></workbook>' % (S, R),
    "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                  '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>',
    "xl/sharedStrings.xml": '<sst %s><si><t>MH</t></si><si><t>Manhole</t></si></sst>' % S,
    "xl/worksheets/sheet1.xml": '<worksheet %s><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v>'
                                '</c><c r="C1"><v>4</v></c></row></sheetData></worksheet>' % S})
office(os.path.join(uk, "Standards", "kickoff.pptx"), {
    "ppt/slides/slide1.xml": '<p:sld %s><a:p><a:r><a:t>Kickoff</a:t></a:r></a:p></p:sld>' % A,
    "ppt/slides/slide2.xml": '<p:sld %s><a:p><a:r><a:t>Two alternatives in every proposal</a:t></a:r></a:p></p:sld>' % A})
with open(os.path.join(elm_dir, "old standard.txt"), "w", encoding="utf-8") as f:
    f.write("from before User Knowledge")
before = sha(elm)
r = P.project_files(None, vce)
by = {x["path"]: x for x in r["files"]}
gpath = os.path.join("Guidelines", "Proposal guide.pdf")
check(r["user_knowledge_folder"] == uk and sorted(by) == sorted([
    "photo.jpg", gpath, os.path.join("Building types", "School requirements.docx"), os.path.join("Standards", "codes.xlsx"),
    os.path.join("Standards", "kickoff.pptx"), os.path.join("Standards", "layers.md")]), "files lists the User Knowledge folder")
check(by[gpath]["read_by_analyzer"] and not by[os.path.join("Standards", "layers.md")]["read_by_analyzer"],
      "...marks the documents Project Analyzer read (same size and modified time)")
check(by[os.path.join("Standards", "codes.xlsx")]["readable_here"] and not by["photo.jpg"]["readable_here"],
      "...and the ones TBC can read itself")
check(r.get("elsewhere") == ["old standard.txt"] and "move" in r.get("elsewhere_hint", ""),
      "files left outside User Knowledge by older versions are listed, to be moved")
g = P.read_file("Guidelines/Proposal guide.pdf", None, vce)
check("two alternatives" in g["text"] and "setback" in g["text"] and "Project Analyzer" in g["read_from"],
      "read: a PDF the analyzer read comes from the project database")
part = P.read_file(gpath, None, vce, max_chars=40)
rest = P.read_file(gpath, None, vce, max_chars=40, offset=part["next_offset"])
check(part.get("truncated") and part["text"] + rest["text"] == g["text"][:80], "read: offset continues a long document")
check(P.read_file("Standards\\layers.md", None, vce)["text"].startswith("# Layer standard"), "read returns a text file")
check(P.read_file("Standards\\layers.md", None, vce, max_chars=5).get("truncated"), "long files are cut at max_chars")
docx = P.read_file(os.path.join("Building types", "School requirements.docx"), None, vce)["text"]
check("classroom wing" in docx and "| Use | Layer |" in docx, "read: a Word file without Project Analyzer (paragraphs, tables)")
check("## Codes" in P.read_file("Standards/codes.xlsx", None, vce)["text"] and
      "MH | Manhole | 4" in P.read_file("Standards/codes.xlsx", None, vce)["text"], "read: an Excel file (sheet names, rows)")
check("## Slide 2\n\nTwo alternatives" in P.read_file("Standards/kickoff.pptx", None, vce)["text"], "read: a PowerPoint file")
check(raises(lambda: P.read_file("..\\..\\elm-street-drainage.db", None, vce), "inside") and
      raises(lambda: P.read_file("..\\old standard.txt", None, vce), "inside"), "paths outside User Knowledge are refused")
check(raises(lambda: P.read_file("photo.jpg", None, vce), "analyze.py knowledge"),
      "a file TBC can't read points to Project Analyzer")
os.utime(guide, (guide_time + 60, guide_time + 60))
check(raises(lambda: P.read_file(gpath, None, vce), "analyze.py knowledge"),
      "a document changed since the analyzer read it isn't served from the database")
os.utime(guide, (guide_time, guide_time))
s = P.search("setback", None, vce)
check([(h["path"], h.get("user_knowledge")) for h in s["documents"]] == [("<user knowledge>\\" + gpath, True)],
      "search finds the analyzer's user-knowledge text, marked user_knowledge")
s = P.search("classroom inlet", None, vce)
check([h["path"] for h in s["documents"] if h.get("not_in_database")] == ["<user knowledge>\\" + os.path.join(
      "Building types", "School requirements.docx")], "search also reads documents the database doesn't have yet")
o = P.overview(None, vce)
u = o["user_knowledge"]
check(u["documents"] == 6 and u["read_by_analyzer"] == 1 and gpath in u["names"] and "name it" in u["hint"],
      "overview lists the user knowledge")
check(o["files_by_status"] == {"done": 8, "duplicate": 1, "failed": 1}, "overview: the job's file counts leave user knowledge out")
check(sha(elm) == before, "reading user knowledge never writes the database")
fresh = P.overview("Phase Two", None)["user_knowledge"]
check(fresh["documents"] == 0 and "Empty" in fresh["hint"] and os.path.isdir(fresh["folder"]),
      "a job only TBC knows (no Project Analyzer) has an empty User Knowledge folder ready")

# --- 7. the overview reaches the AI once per job -----------------------------------------------------------------
P.reset_announcements()
first = P.notes_once(vce) or {}
check(first.get("project") == "Elm Street Drainage" and [c["id"] for c in first.get("checks_high", [])] == ["check-1"]
      and first.get("missing_files") == 1, "the first result carries the job's high checks and missing-file count")
check(sorted(f["id"] for f in first.get("key_facts", [])) == ["fact-1", "fact-3", "fact-5"] and "fact-5" in [f["id"] for f in first.get("tbc_facts", [])],
      "...its key facts and TBC's own facts")
check("12+50" in first.get("hint", "") and "COPIED FOLDER" in first.get("copied_folder", ""), "...with the reference formats and the copy hint")
check(os.path.join("Guidelines", "Proposal guide.pdf") in first.get("user_knowledge", []) and
      "user_knowledge" in first.get("hint", ""), "...and the names of the user's own documents for the job")
check("Reference only" in first.get("reference_only", ""), "...and the reference-only rule")
check(P.notes_once(vce) is None, "...and only once per server run")
check(P.in_shared(P.projects_dir()) and P.in_shared(os.path.join(P.shared_root(), "x", "y.csv"))
      and not P.in_shared(job) and not P.in_shared(P.shared_root() + "-other"),
      "in_shared: the shared folder and what's inside it, not a job folder or a look-alike name")
check(P.notes_once(os.path.join(work, "nowhere", "a.vce")) is None, "no job, no overview")

# --- 8. which shared folder (contract "Where"): nothing is created, renamed or moved ----------------------------
docs = os.path.join(work, "Documents")
os.makedirs(docs)
saved_env = os.environ.pop("PROJECT_KNOWLEDGE_DIR")
check(K.shared_dir(docs) == os.path.join(docs, "Project Knowledge") and not os.listdir(docs),
      "a new PC gets Documents\\Project Knowledge (nothing created)")
os.makedirs(os.path.join(docs, "Civil3DMcp"))
check(K.shared_dir(docs) == os.path.join(docs, "Civil3DMcp"), "the pre-2.2.0 folder is used as it is")
os.makedirs(os.path.join(docs, "Civil3DMcp-KnowledgeBase"))
check(K.shared_dir(docs) == os.path.join(docs, "Civil3DMcp-KnowledgeBase"), "an existing Civil3DMcp-KnowledgeBase is used as it is")
os.makedirs(os.path.join(docs, "Project Knowledge"))
check(K.shared_dir(docs) == os.path.join(docs, "Project Knowledge"), "once renamed to Project Knowledge, that's the one used")
os.environ["CIVIL3D_KNOWLEDGE_DIR"] = os.path.join(work, "old-variable")
check(K.shared_dir(docs) == os.path.join(work, "old-variable"), "CIVIL3D_KNOWLEDGE_DIR (the earlier name) still works")
os.environ["PROJECT_KNOWLEDGE_DIR"] = saved_env
check(K.shared_dir(docs) == saved_env, "PROJECT_KNOWLEDGE_DIR comes first")
del os.environ["CIVIL3D_KNOWLEDGE_DIR"]
check(sorted(os.listdir(docs)) == ["Civil3DMcp", "Civil3DMcp-KnowledgeBase", "Project Knowledge"], "no folder was moved")

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

# --- 10. the new read actions and the SQL-side reads, on the fixture -------------------------------------------
check(P.series_key("C-101 rev2 (2).dwg") == "c 101" and P.series_key("Site Plan current copy.pdf") == "site plan",
      "series_key matches the analyzer's (dates, rev N, current, (2) taken out)")
r = P.latest("C-104", None, vce)
check(r["series"] == [] and "no version list" in r["hint"], "latest: no version list yet -> a hint, no error")
for row in (("s1", "c 104", "cad", 1, "0000000000000003", "Drawings\\Old\\C-104 rev1.dwg", "2026-09-01T10:00:00.000Z", None, "1", 0, None),
            ("s1", "c 104", "cad", 2, "0000000000000003", "Drawings\\C-104 rev2.dwg", "2026-10-01T10:00:00.000Z", None, "2", 0, None),
            ("s1", "c 104", "cad", 3, "0000000000000003", "Drawings\\C-104.dwg", "2026-10-10T10:00:00.000Z", "2026-10-10", "3", 1, None),
            ("s2", "c 104", "pdf", 1, None, "Plots\\C-104.pdf", "2026-10-11T10:00:00.000Z", None, None, 1, None)):
    sql(elm, "INSERT INTO intel_series(series_id, key, kind, position, file_id, path, modified, title_date, revision, latest, note) "
             "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
with open(os.path.join(job, "Drawings", "C-104.dwg"), "w") as f:
    f.write("x")
r = P.latest("C-104", None, vce)
s1 = r["series"][0]
check([x["kind"] for x in r["series"]] == ["cad", "pdf"] and s1["versions"] == 3 and s1["latest"]["path"] == "Drawings\\C-104.dwg",
      "latest: by series key, drawings first, the one modified last")
check(s1["latest"]["absolute"] == os.path.join(job, "Drawings", "C-104.dwg") and s1["latest"]["exists"] and
      s1["latest"]["modified"] == "2026-10-10" and s1["latest"]["revision"] == "3" and s1["folders"] == 2,
      "latest: full path, modified date, revision, folders")
check([x["path"] for x in s1["older"]] == ["Drawings\\C-104 rev2.dwg", "Drawings\\Old\\C-104 rev1.dwg"], "latest: older ones newest first")
check([len(x["series"]) for x in (P.latest("drawings/c-104.dwg", None, vce), P.latest("c-104 rev2.dwg", None, vce),
                                    P.latest("C-104 rev 7.dwg", None, vce))] == [1, 1, 2],
      "latest: an exact path (any case, any slashes) or a file name picks its series; else the series key")
r = P.latest("C-104", None, vce, near="old")
check(len(r["series"]) == 1 and r["series"][0]["latest"]["path"] == "Drawings\\Old\\C-104 rev1.dwg", "latest: near keeps the folder's members")
check(P.latest("Nothing Like It", None, vce)["series"] == [] and raises(lambda: P.latest(" ", None, vce), "name is required"),
      "latest: an unknown name says so, an empty one is refused")

r = P.checks(None, vce)
check([c["id"] for c in r["checks"]] == ["check-1", "check-2"] and r["by_severity"] == {"high": 1, "medium": 1}
      and r["by_kind"] == {"missing file": 1, "no reply": 1} and r["total"] == 2, "checks: high first, with counts by severity and kind")
check(r["checks"][0]["files"] == ["Drawings\\C-104.dwg"] and r["checks"][1]["files"] == ["Email\\RFI 12.msg"]
      and r["checks"][1]["refs"] == ["RFI 12"], "checks: file ids become paths")
check([c["id"] for c in P.checks(None, vce, severity="HIGH")["checks"]] == ["check-1"]
      and [c["id"] for c in P.checks(None, vce, kind="No Reply")["checks"]] == ["check-2"], "checks: severity and kind filters (any case)")
r = P.checks(None, vce, limit=1)
check(len(r["checks"]) == 1 and r.get("more"), "checks: limit, with how many more")
sql(elm, "INSERT INTO intel_checks(id, severity, kind, title, detail, refs, files) VALUES (?, ?, ?, ?, ?, ?, ?)",
    ("check-9", "info", "amounts", "CO 4 amounts differ", "$12,500.00 vs $12,050.00", "[]",
     json.dumps(["0000000000000001"] * 12 + ["ffffffffffffffff"])))
c9 = P.checks(None, vce, severity="info")["checks"][0]
check(len(c9["files"]) == P.MAX_CHECK_FILES and c9["more_files"] == 3, "checks: at most %d paths per check" % P.MAX_CHECK_FILES)

check(P.changes(None, vce, since="2026")["requirement_changes"] == [] and "No changes" in P.changes(None, vce)["hint"],
      "changes: none yet -> a hint")
sql(elm, "INSERT INTO intel_events(date, precision, kind, confidence, title, file_id, location) VALUES "
         "('2026-10-20', 'day', 'change', 'medium', 'Going forward use 18 inch pipe at MH-3', '0000000000000001', 'p.1'), "
         "('2026-09-02', 'day', 'change', 'high', 'Revised spec: 36 inch culvert no longer required', '0000000000000002', NULL)")
sql(elm, "INSERT INTO file_changes(file_id, path, change, seen, mtime, summary, details) VALUES "
         "('0000000000000003', 'Drawings\\C-104.dwg', 'changed', '2026-10-21T10:00:00.000Z', '2026-10-20T09:00:00.000Z', "
         "'title block revision 2 -> 3', '{\"lines_added\": 12}')")
r = P.changes(None, vce, since="2026-09")
check([x["date"] for x in r["requirement_changes"]] == ["2026-10-20", "2026-09-02"] and r["requirement_changes_total"] == 2
      and r["requirement_changes"][0]["path"] == "Documents\\minutes.docx", "changes: requirement changes newest first, with paths")
check(r["file_changes"][0]["summary"] == "title block revision 2 -> 3" and r["file_changes"][0]["details"] == {"lines_added": 12}
      and r["file_changes_total"] == 1, "changes: the file_changes rows, details parsed")
check([x["date"] for x in P.changes(None, vce, since="2026-10")["requirement_changes"]] == ["2026-10-20"], "changes: since a date")
r = P.changes(None, vce, file="documents\\SPECS.pdf")
check(r["since"] is None and [x["date"] for x in r["requirement_changes"]] == ["2026-09-02"] and r["file_changes"] == [],
      "changes: one file, all time")
check(P.changes(None, vce)["since"] == (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
      and raises(lambda: P.changes(None, vce, since="9/1/26"), "yyyy"), "changes: the last 30 days by default; ISO dates only")

t = P.timeline(None, vce)
dates = [x["date"] for x in t["events"]]
check(dates == sorted(dates) and len(dates) == 7, "timeline: events (SQL-ordered) and dated facts merged in order")
october = P.timeline(None, vce, "2026-10", "2026-10")["events"]
check(october and all(x["date"].startswith("2026-10") for x in october) and len(october) == sum(d.startswith("2026-10") for d in dates),
      "timeline: a YYYY-MM end takes in that whole month")
r = P.timeline(None, vce, limit=2)
check(len(r["events"]) == 2 and r["more"].startswith("5 more") and [x["date"] for x in r["events"]] == dates[:2],
      "timeline: limit is applied in SQL, the rest counted")
check(P.entity("structure:mh-3", None, vce)["found"] and P.entity("mh-3", None, vce)["entity"]["name"] == "MH-3",
      "entity: by id, or by name in any case")
e = P.entity("john smith", None, vce)
check([x["title"] for x in e["events"]][:1] == ["Drainage design review"] and len(e["events"]) == 3
      and e["stories"][0]["steps"][0]["who"] == "Robin Lee", "entity: events of its files (SQL), stories with steps (one query)")
check(P.locate("P:\\JOBS\\1234 ELM ST\\CAD\\topo.dwg", None, vce)["status"] == "found", "locate: by the normalized path, any case")
plan = " ".join(str(x[-1]) for x in sql(elm, "EXPLAIN QUERY PLAN SELECT * FROM refs WHERE normalized = ? COLLATE NOCASE", ("x",)))
plan += " " + " ".join(str(x[-1]) for x in sql(elm, "EXPLAIN QUERY PLAN SELECT * FROM intel_entities WHERE name = ? COLLATE NOCASE", ("x",)))
check("refs_normalized_nocase" in plan and "intel_entities_name" in plan, "the NOCASE lookups use the schema's indexes")

# --- 11. opening: indexes added by a write, journal mode, read-only opens ----------------------------------------
old = os.path.join(projects_dir, "old-index-job.db")
shutil.copy(os.path.join(fixtures, "fixture.db"), old)
sql(old, "UPDATE meta SET value = 'Old Index Job' WHERE key = 'project_name'")
sql(old, "UPDATE meta SET value = ? WHERE key = 'source_root'", (os.path.join(work, "jobs", "Old Index"),))
schema_indexes = [line.split()[5] for line in open(P.SCHEMA_FILE, encoding="utf-8") if line.startswith("CREATE INDEX IF NOT EXISTS")]
readers = schema_indexes[-11:]  # the readers' indexes at the end of the schema, missing in an older database
for ix in readers:
    sql(old, "DROP INDEX %s" % ix)
have = lambda: {r[0] for r in sql(old, "SELECT name FROM sqlite_master WHERE type = 'index'")}  # noqa: E731
old_sha = sha(old)
P.overview("Old Index Job", None)
check(sha(old) == old_sha and not set(readers) & have(), "a read of an older database adds nothing")
P.add_note("Index check note", "Old Index Job", None)
check(set(schema_indexes) <= have() and sql(old, "PRAGMA journal_mode")[0][0] == "wal",
      "a write adds the schema's indexes (%d) and switches it to WAL" % len(schema_indexes))
check(readers[0] == "files_path_nocase" and readers[-1] == "intel_story_steps_story" and "intel_events_date" in readers,
      "the schema's index lines are read from project-db.sql")
check(raises(lambda: P.connect(os.path.join(projects_dir, "nothing-here.db")), "no project database")
      and not os.path.exists(os.path.join(projects_dir, "nothing-here.db")), "a read of a missing database creates nothing")

# --- 12. a busy database: a friendly error after one retry -------------------------------------------------------
P.BUSY_TIMEOUT, P.BUSY_RETRY_DELAY = 0.2, 0.05
busy = os.path.join(projects_dir, "busy-job.db")
shutil.copy(os.path.join(fixtures, "fixture.db"), busy)
sql(busy, "UPDATE meta SET value = 'Busy Job' WHERE key = 'project_name'")
P.overview("Busy Job", None)  # known to the job index before the lock is taken
hold = sqlite3.connect(busy, isolation_level=None)
hold.execute("BEGIN EXCLUSIVE")
import time  # noqa: E402
started = time.time()
check(raises(lambda: P.overview("Busy Job", None), "database is busy") and time.time() - started < 5,
      "a read of a locked database: 'busy, try again in a moment' (one retry, quickly)")
check(raises(lambda: P.add_note("Busy note", "Busy Job", None), "project analyzer is probably writing"), "...and a write")
hold.execute("ROLLBACK")
sql(busy, "PRAGMA journal_mode = WAL")
hold.execute("BEGIN IMMEDIATE")
check(P.overview("Busy Job", None)["project"] == "Busy Job", "in WAL a reader isn't blocked by another tool's write")
check(raises(lambda: P.add_note("Busy note", "Busy Job", None), "busy"), "...but a second writer gets the friendly busy error")
hold.execute("ROLLBACK")
check(P.add_note("Busy note", "Busy Job", None)["action"] == "added", "once the lock is gone the write goes through")
hold.close()
P.BUSY_TIMEOUT, P.BUSY_RETRY_DELAY = 10.0, 0.5

# --- 13. a damaged database: never read on, written or set up again; listed with a note ---------------------------
damaged = os.path.join(projects_dir, "damaged-job.db")
shutil.copy(os.path.join(fixtures, "fixture.db"), damaged)
page = sql(damaged, "PRAGMA page_size")[0][0]
with open(damaged, "r+b") as f:  # garbage over every page but the first (the header and the start of the schema)
    size = os.path.getsize(damaged)
    f.seek(page)
    f.write(bytes((i * 37 + 11) % 256 for i in range(size - page)))
os.makedirs(os.path.join(projects_dir, "damaged-job.backups"))
older_copy = os.path.join(projects_dir, "damaged-job.backups", "damaged-job 2026-10-01 101010.db")
newest_copy = os.path.join(projects_dir, "damaged-job.backups", "damaged-job 2026-10-02 090000.db")
for copy in (older_copy, newest_copy):
    shutil.copy(os.path.join(fixtures, "fixture.db"), copy)
damaged_sha = sha(damaged)
P.forget_jobs()
listed = {j["name"]: j for j in P.list_notes(None, os.path.join(work, "nowhere", "a.vce"))["known_projects"]}
check("damaged-job" in listed and "can't be read" in listed["damaged-job"].get("damaged", "")
      and "Elm Street Drainage" in listed, "the job list shows a damaged job with a note (it doesn't vanish)")
try:
    P.overview("damaged-job", None)
    message = ""
except K.KnowledgeError as ex:
    message = str(ex)
check("is damaged" in message and 'analyze.py restore --project "damaged-job"' in message and newest_copy in message,
      "a read: 'damaged', how to restore with Project Analyzer, and the newest backup")
check(raises(lambda: P.add_note("x", "damaged-job", None), "is damaged") and raises(lambda: P.link("damaged-job", job, None), "is damaged"),
      "a write is refused the same way (never set up again over itself)")
check(sha(damaged) == damaged_sha and not os.path.exists(damaged + "-wal") and P.quick_check(damaged) != "ok",
      "the damaged file is left exactly as it was")
check(P.notes_once(os.path.join(work, "nowhere", "a.vce")) is None, "a damaged job never breaks the first-result overview")
os.remove(older_copy)
os.remove(newest_copy)
check(raises(lambda: P.overview("damaged-job", None), "there is no backup"), "without backups it says so")

# --- 13b. damage is remembered: a write that wouldn't touch the damaged pages is refused too -----------------------


def spoil(path):
    """0xFF over pages 4-11 (pages adding a note doesn't touch)."""
    with open(path, "r+b") as f:
        f.seek(4096 * 3)
        f.write(b"\xff" * 4096 * 8)


partly = os.path.join(projects_dir, "partly-damaged.db")
shutil.copy(os.path.join(fixtures, "fixture.db"), partly)
sql(partly, "UPDATE meta SET value = 'Partly Damaged Job' WHERE key = 'project_name'")
spoil(partly)
partly_sha = sha(partly)
check(raises(lambda: P.overview("Partly Damaged Job", None), "is damaged"), "a read finds the damage")
check(raises(lambda: P.add_note("Note into a damaged file", "Partly Damaged Job", None), "is damaged") and sha(partly) == partly_sha,
      "...and a write after it is refused too, the file unchanged (the damage is remembered)")
shutil.copy(os.path.join(fixtures, "fixture.db"), partly)  # as if a backup was put back
sql(partly, "UPDATE meta SET value = 'Partly Damaged Job' WHERE key = 'project_name'")
check(P.add_note("Note after the restore", "Partly Damaged Job", None)["action"] == "added" and P.known_damage(partly) is None,
      "once the file is replaced with a good copy, writes work again")
pine = os.path.join(work, "jobs", "Pine Lane")
os.makedirs(pine)
P.link("Pine Lane Survey", pine, None)  # created by TBC: no source_root, so its first write of the day is backed up
pine_db = os.path.join(projects_dir, "pine-lane-survey.db")
spoil(pine_db)
pine_sha = sha(pine_db)
check(raises(lambda: P.add_note("First note of the day", "Pine Lane Survey", None), "is damaged") and sha(pine_db) == pine_sha,
      "a backup copy that fails its check stops the write (the source is damaged), the file unchanged")
pine_backups = os.path.join(projects_dir, "pine-lane-survey.backups")
check(os.path.isdir(pine_backups) and not os.listdir(pine_backups) and P.known_damage(pine_db),
      "...found by the backup (no copy kept), and remembered")
check(raises(lambda: P.add_note("Second try", "Pine Lane Survey", None), "is damaged") and sha(pine_db) == pine_sha,
      "...so the next write is refused at once")

# --- 14. TBC's daily backup of a database it looks after alone ---------------------------------------------------
import re  # noqa: E402
bjob = os.path.join(work, "jobs", "Backup Job")
os.makedirs(bjob)
P.link("Backup Job", bjob, None)
bdir = os.path.join(projects_dir, "backup-job.backups")
check(not os.path.isdir(bdir), "creating a database makes no backup of it")
P.add_note("Before the first backup", "Backup Job", None)
copies = sorted(os.listdir(bdir)) if os.path.isdir(bdir) else []
today = datetime.date.today().isoformat()
check(len(copies) == 1 and re.match(r"^backup-job %s \d{6}\.db$" % today, copies[0]), "the first write of the day makes a copy: %s" % copies)
check(P.quick_check(os.path.join(bdir, copies[0])) == "ok" and sql(os.path.join(bdir, copies[0]), "SELECT COUNT(*) FROM facts")[0][0] == 0,
      "...checked, taken before the write")
P.add_note("Second note today", "Backup Job", None)
P._backed_up.clear()  # as after a restart of the server: today's copy is found by its name
P.add_note("Third note today", "Backup Job", None)
check(len(os.listdir(bdir)) == 1, "one copy a day")
os.rename(os.path.join(bdir, copies[0]), os.path.join(bdir, "backup-job 2026-01-04 100000.db"))
for day in ("01", "02", "03"):
    shutil.copy(os.path.join(bdir, "backup-job 2026-01-04 100000.db"), os.path.join(bdir, "backup-job 2026-01-%s 100000.db" % day))
for other in ("other-job 2025-01-01 100000.db", "notes.txt"):
    with open(os.path.join(bdir, other), "w") as f:
        f.write("not ours")
P._backed_up.clear()
P.add_note("Fourth note, the next day", "Backup Job", None)
left = sorted(os.listdir(bdir))
check([n for n in left if n.startswith("backup-job ")][:2] == ["backup-job 2026-01-03 100000.db", "backup-job 2026-01-04 100000.db"]
      and len([n for n in left if n.startswith("backup-job ")]) == 3, "the newest 3 copies are kept: %s" % left)
check("other-job 2025-01-01 100000.db" in left and "notes.txt" in left and not [n for n in left if n.endswith(".partial")],
      "only its own older copies are deleted")
check(not os.path.isdir(os.path.join(projects_dir, "elm-street-drainage.backups")),
      "a database Project Analyzer looks after (source_root set) gets no TBC backup")

# --- 15. User Knowledge: long paths, unreadable files; no zstandard ---------------------------------------------
deep_rel = os.path.join(*["deep folder %02d" % i for i in range(14)], "deep standard.md")
deep = os.path.join(uk, deep_rel)
os.makedirs("\\\\?\\" + os.path.dirname(deep), exist_ok=True)
with open("\\\\?\\" + deep, "w", encoding="utf-8") as f:
    f.write("Deep inlets need a sump.")
check(len(deep) > 260, "a User Knowledge file with a path of %d characters" % len(deep))
r = P.project_files(None, vce)
check(deep_rel in [x["path"] for x in r["files"]] and "unreadable" not in r, "files lists it (the \\\\?\\ form)")
check(P.read_file(deep_rel, None, vce)["text"] == "Deep inlets need a sump.", "read opens it")
check("<user knowledge>\\" + deep_rel in [h["path"] for h in P.search("sump", None, vce)["documents"]], "search reads it")
real_stat = os.stat


def flaky_stat(path, *args, **kwargs):
    if str(path).endswith("layers.md"):
        raise PermissionError(13, "Permission denied", path)
    return real_stat(path, *args, **kwargs)


os.stat = flaky_stat
try:
    r = P.project_files(None, vce)
    o = P.overview(None, vce)
finally:
    os.stat = real_stat
check(os.path.join("Standards", "layers.md") not in [x["path"] for x in r["files"]] and len(r["files"]) == 6
      and r["unreadable"]["files"][0]["path"] == os.path.join("Standards", "layers.md"), "a file that can't be read is left out with a note")
check(o["user_knowledge"].get("unreadable") and o["user_knowledge"]["documents"] == 6, "...in the overview too, which still works")
P._zstd[0] = False  # as without the zstandard package
try:
    s = P.search("MH-3", None, vce)
    g = P.read_file(gpath, None, vce)
    f = P.file_info("documents/specs.pdf", None, vce)
finally:
    P._zstd[0] = None
check(s["documents"] and any(h["snippet"] is None for h in s["documents"]) and "pip install zstandard" in s.get("text_error", ""),
      "search without zstandard: the hits, without snippets, and how to install it")
check(g["text"] == "" and "to read the stored text" in g.get("text_error", "") and g["file"] == gpath,
      "read without zstandard: what it can, and how to install it")
check("text" not in f and "pip install zstandard" in f.get("text_error", "") and f["file"]["id"], "file without zstandard: the details")

# --- 16. TBC MCP installed alone: an empty shared folder, no fixture, no other tool --------------------------------
alone = os.path.join(work, "alone-shared")
os.environ["PROJECT_KNOWLEDGE_DIR"] = alone
P.forget_jobs()
alone_job = os.path.join(work, "jobs", "Maple Court")
os.makedirs(os.path.join(alone_job, "TBC"))
alone_vce = os.path.join(alone_job, "TBC", "Maple.vce")
answers, problems = {}, []
for label, action in (
        ("list before", lambda: P.list_notes(None, alone_vce)),
        ("link", lambda: P.link("Maple Court Survey", None, alone_vce)),
        ("add", lambda: P.add_note("Control points CP-1 and CP-2 set 2026-10-03", None, alone_vce, source="user", date="2026-10-03")),
        ("list", lambda: P.list_notes(None, alone_vce)), ("overview", lambda: P.overview(None, alone_vce)),
        ("search", lambda: P.search("control", None, alone_vce)), ("file", lambda: P.file_info("C-101.dwg", None, alone_vce)),
        ("entity", lambda: P.entity("CP-1", None, alone_vce)), ("timeline", lambda: P.timeline(None, alone_vce)),
        ("locate", lambda: P.locate("P:\\Jobs\\1234 Elm St\\x.dwg", None, alone_vce)),
        ("latest", lambda: P.latest("C-101", None, alone_vce)), ("checks", lambda: P.checks(None, alone_vce)),
        ("changes", lambda: P.changes(None, alone_vce)), ("files", lambda: P.project_files(None, alone_vce)),
        ("read", lambda: P.read_file("guide.md", None, alone_vce)), ("once", lambda: P.notes_once(alone_vce))):
    try:
        answers[label] = action()
    except K.KnowledgeError as ex:
        answers[label] = str(ex)  # a message for the AI is a friendly answer too
    except Exception as ex:
        problems.append("%s: %s: %s" % (label, type(ex).__name__, ex))
check(not problems, "installed alone: every action answers without an exception %s" % problems)
check(answers["link"]["action"] == "created" and answers["add"]["action"] == "added" and answers["timeline"]["events"][0]["kind"] == "fact"
      and answers["search"]["facts"] and "no version list" in answers["latest"]["hint"] and "No checks" in answers["checks"]["hint"]
      and "No changes" in answers["changes"]["hint"] and answers["locate"]["status"] == "not known", "installed alone: the answers make sense")
check("Use action=search" in answers["file"] and "No file" in answers["read"] and answers["overview"]["practices"] == [],
      "installed alone: a missing file is a message, not a crash")
alone_made = set(os.listdir(os.path.join(alone, "projects"))) - {"maple-court-survey.db-wal", "maple-court-survey.db-shm"}
check(alone_made == {"maple-court-survey", "maple-court-survey.db", "maple-court-survey.backups"},
      "...and only the job's database, its folder and its daily backup were made: %s" % sorted(alone_made))
os.environ["PROJECT_KNOWLEDGE_DIR"] = shared
P.forget_jobs()

# --- 17. knowledge files: locks, concurrent writers, a bad lessons line, temp files, backups ----------------------
K.LOCK_WAIT = 0.5
dead = subprocess.Popen([sys.executable, "-c", "pass"])
dead.wait()
lock = K.MEMORY + ".lock"
os.makedirs(os.path.dirname(K.MEMORY), exist_ok=True)
with open(lock, "w") as f:
    f.write(str(dead.pid))
check(K.add_lesson("Stale locks are taken over when their process is gone")["id"] and not os.path.exists(lock),
      "a lock left by a process that is gone is taken over (and released)")
with open(lock, "w") as f:
    f.write(str(os.getpid()))
check(raises(lambda: K.add_lesson("Waits for a live lock"), "stayed locked"), "a live lock is waited for, then a clear error")
os.utime(lock, (time.time() - 120, time.time() - 120))
check(K.add_lesson("A lock older than a minute is taken over")["id"], "a lock older than a minute is taken over")
import threading  # noqa: E402


def lessons_from(n):
    for i in range(15):
        K.add_lesson("Thread lesson %d-%d about panels" % (n, i))


threads = [threading.Thread(target=lessons_from, args=(n,)) for n in range(3)]
for t in threads:
    t.start()
for t in threads:
    t.join()
worker = ("import sys; sys.path.insert(0, %r); import knowledge as K\n"
          "for i in range(15): K.add_lesson('Process lesson %%s-%%d about panels' %% (sys.argv[1], i))" % os.path.join(repo, "mcp_server"))
procs = [subprocess.Popen([sys.executable, "-c", worker, str(n)], env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")) for n in range(2)]
for pr in procs:
    pr.wait(timeout=120)
learned = K._read_jsonl(K.MEMORY)
texts = [l["text"] for l in learned]
check(sum(t.startswith("Thread lesson") for t in texts) == 45 and sum(t.startswith("Process lesson") for t in texts) == 30
      and all(pr.returncode == 0 for pr in procs), "3 threads and 2 processes adding lessons at once lose nothing")
check(len({l["id"] for l in learned}) == len(learned), "...and every lesson has its own id")
with open(K.MEMORY, "ab") as f:
    f.write(b"\xff\xfe not utf-8\n{not json\n[1, 2]\n")
count = len(K.list_lessons())
check(count >= 78 and K.skipped_lines() == 3, "bad lessons.jsonl lines are skipped and counted (%d)" % K.skipped_lines())
with open(K.MEMORY, "ab") as f:
    f.write(b'{"torn": "line without its newline')
added = K.add_lesson("A lesson after a torn line")
check(added["text"] in [l["text"] for l in K.list_lessons()], "a lesson added after a torn last line is still read")
gone = K.delete_lesson(added["id"])
check(gone == {"deleted": added["id"]} and os.path.isfile(K.MEMORY + ".bak1"), "rewriting lessons keeps the old file as .bak1")
for n in range(5):
    K.update_pref(K.add_pref("Use numeric point IDs for new points")["id"], "Use numeric point IDs for new points (%d)" % n)
check(sorted(n for n in os.listdir(K.USER_ROOT) if n.startswith("preferences.json.bak")) ==
      ["preferences.json.bak1", "preferences.json.bak2", "preferences.json.bak3"], "preferences keep their last 3 versions")
check(os.path.isfile(practices_path + ".bak1") and not [n for n in os.listdir(shared) if n.endswith(".lock")],
      "practices keep a .bak, no lock file is left behind")
old_tmp = os.path.join(K.USER_ROOT, "commands", ".x.json.123.456.tmp")
new_tmp = os.path.join(K.USER_ROOT, ".preferences.json.123.789.tmp")
os.makedirs(os.path.dirname(old_tmp), exist_ok=True)
for t in (old_tmp, new_tmp, os.path.join(K.USER_ROOT, "keep.tmp")):
    with open(t, "w") as f:
        f.write("{")
os.utime(old_tmp, (time.time() - 7200, time.time() - 7200))
os.utime(os.path.join(K.USER_ROOT, "keep.tmp"), (time.time() - 7200, time.time() - 7200))
check(K.sweep_temp_files(K.USER_ROOT) == 1 and not os.path.exists(old_tmp) and os.path.exists(new_tmp)
      and os.path.exists(os.path.join(K.USER_ROOT, "keep.tmp")), "temp files of crashed writes are swept after an hour (only ours)")
K.LOCK_WAIT = 5.0

# --- 18. the server, over stdio, without TBC ------------------------------------------------------------------
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
check(init["serverInfo"]["version"] == "0.5.0", "server version 0.5.0")
check("REFERENCE ONLY" in ins and "which file is current" in ins,
      "instructions say the job database is for reference only and to ask for the current file")
check("THREE KINDS OF KNOWLEDGE" in ins and "tbc_practices" in ins and "tbc_project_notes" in ins, "instructions explain the three kinds of knowledge")
check("Use numeric point IDs for new points" in ins and "GOOD PRACTICES" in ins and "[practice-1] Storm pipe minimum slope" in ins,
      "instructions carry the user's preferences and the suite's practices")
tools = {t["name"]: t for t in rpc(2, "tools/list", {})["tools"]}
check("tbc_project_notes" in tools and "tbc_practices" in tools, "tbc_project_notes and tbc_practices are listed (%d tools)" % len(tools))
check(set(tools["tbc_project_notes"]["inputSchema"]["properties"]["action"]["enum"]) ==
      {"list", "overview", "search", "file", "entity", "timeline", "locate", "latest", "checks", "changes", "link", "unlink",
       "add", "update", "remove", "files", "read"}, "tbc_project_notes offers every action")
desc = tools["tbc_project_notes"]["description"]
check(all(s in desc for s in ("12+50", "MH-3", "C-104", "RFI 12", "$12,500.00", "license", "supersedes", "tbc_memory", "tbc_practices")),
      "the tool tells the AI the reference formats, privacy, supersedes and where other knowledge goes")
check(all(s in desc for s in ("locate", "never guess", "BEFORE telling the user", "overview", "search", "entity", "timeline",
                               "latest", "checks", "changes", "busy")), "the tool says when to use locate and the read actions")
err, r = call(3, "tbc_project_notes", {"action": "overview", "project": "Elm Street Drainage"})
check(not err and r["project"] == "Elm Street Drainage" and r["checks_high"], "overview of a named job works without TBC")
check("Reference only" in r.get("reference_only", "") and "ask which file is current" in r["reference_only"],
      "a job-database answer says it is for reference only and to ask for the current file")
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
err, r = call(16, "tbc_import", {"action": "scan", "folder": P.projects_dir()})
check(err and "reference only" in r and "current source file" in r, "an import from the shared knowledge folder is refused")
err, r = call(12, "tbc_project_notes", {"action": "checks", "project": "Elm Street Drainage", "severity": "high"})
check(not err and [c["id"] for c in r["checks"]] == ["check-1"], "checks over MCP")
err, r = call(13, "tbc_project_notes", {"action": "latest", "project": "Elm Street Drainage", "name": "C-104"})
check(not err and r["series"][0]["latest"]["path"] == "Drawings\\C-104.dwg", "latest over MCP")
err, r = call(14, "tbc_project_notes", {"action": "changes", "project": "Elm Street Drainage", "since": "2026-10"})
check(not err and r["requirement_changes"] and r["file_changes"], "changes over MCP")
err, r = call(15, "tbc_project_notes", {"action": "overview", "project": "damaged-job"})
check(err and "damaged" in r and "analyze.py restore" in r, "a damaged database over MCP: a clear error, not SQLite's")
err, r = call(10, "tbc_practices", {"action": "search", "query": "slope"})
check(not err and r["practices"][0]["id"] == "practice-1", "tbc_practices over MCP")
err, r = call(11, "tbc_memory", {"action": "add", "text": "Elm Street Drainage uses US feet", "topic": "units"})
check(err and "tbc_project_notes action=add" in r, "tbc_memory refuses job data and points to the project notes")
p.stdin.close()
p.wait(timeout=10)

shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if ok else 1)
