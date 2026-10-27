# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Tests TBC MCP's software know-how without TBC (mcp_server/knowledge.py): the built-in layer in the repository's
knowledge\\ is read only, everything learned goes to TBC_MCP_KNOWLEDGE_DIR (else <shared>\\tbc), and reads merge
the two with the learned version winning. Also the general-knowledge rules (duplicates, lessons surfacing by
command, the job-data guard), and that a whole session of writes leaves the repository untouched.

Needs TBC
    No. A made-up built-in layer and the learned layer live in a temporary folder; the last part runs the real
    repository's built-ins with only CIVIL3D_KNOWLEDGE_DIR set (a temporary folder) and checks nothing in the
    repository changed.

How to run
    py -3.12 tests\\test_knowledge_split.py
PASS/FAIL per check; exit code 0 when all pass, else 1.
"""
import json, os, shutil, site, subprocess, sys, tempfile

here = os.path.dirname(os.path.abspath(__file__))
repo = os.path.normpath(os.path.join(here, ".."))
server = os.path.join(repo, "mcp_server", "tbc_mcp_server.py")
work = tempfile.mkdtemp(prefix="tbc_mcp_split_test_")
os.environ.setdefault("PYTHONUSERBASE", site.getuserbase())  # keep pip --user packages when APPDATA is redirected
for var in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
    os.environ[var] = os.path.join(work, "private", var)
    os.makedirs(os.environ[var])
os.environ.pop("TBC_MCP_USER_DIR", None)
shared = os.path.join(work, "shared")
learned = os.path.join(work, "learned")
builtin = os.path.join(work, "builtin")
os.environ["CIVIL3D_KNOWLEDGE_DIR"] = shared
os.environ["TBC_MCP_KNOWLEDGE_DIR"] = learned
sys.path.insert(0, os.path.join(repo, "mcp_server"))
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


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def snapshot(root):
    """Every file under root with its size and modified time."""
    out = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in (".git", "__pycache__")]
        for fn in fns:
            full = os.path.join(dp, fn)
            st = os.stat(full)
            out[os.path.relpath(full, root)] = (st.st_size, st.st_mtime_ns)
    return out


# --- a made-up built-in layer ---------------------------------------------------------------------------------
write(os.path.join(builtin, "skills", "points", "shipped_skill.skill.md"),
      "---\nname: shipped_skill\ncategory: points\ndescription: \"Shipped how-to\"\ntbc_versions: [\"2026.10\"]\n---\n\nShipped steps.\n")
write(os.path.join(builtin, "scripts", "shipped_script.py"),
      K.build_script("shipped_script", "Shipped script", "read", [], "result = 1"))
write(os.path.join(builtin, "memory", "lessons.jsonl"),
      json.dumps({"id": 1, "ts": "2026-10-01T00:00:00", "topic": "createlinestring", "tags": [], "text": "Shipped lesson about vertices",
                  "tbc_version": "2026.10"}) + "\n" +
      json.dumps({"id": 2, "ts": "2026-10-01T00:00:00", "topic": "general", "tags": [], "text": "Shipped lesson two",
                  "tbc_version": "2026.10"}) + "\n")
write(os.path.join(builtin, "commands", "createlinestring.json"),
      json.dumps({"key": "createlinestring", "caption": "Create Linestring", "fields": [], "buttons": [], "notes": [],
                  "tbc_version": "2026.10"}))
write(os.path.join(builtin, "preferences.json"),
      json.dumps([{"id": 1, "topic": "points", "text": "Shipped preference", "added": "2026-10-01T00:00:00"}]))
write(os.path.join(builtin, "skills", "survey", "other_skill.skill.md"), "---\nname: other_skill\ncategory: survey\n---\n\nOld steps.\n")
K.BUILTIN_ROOT = builtin
built_before = snapshot(builtin)

check(K.USER_ROOT == os.path.normpath(learned) and K.PREFS.startswith(learned), "TBC_MCP_KNOWLEDGE_DIR is the learned layer")

# --- skills ----------------------------------------------------------------------------------------------------
skills = {s["name"]: s for s in K.list_skills()}
check(skills.get("shipped_skill", {}).get("layer") == "built-in", "a built-in skill is listed, marked built-in")
check(raises(lambda: K.save_skill("shipped_skill", "points", "d", "New steps."), "already exists"), "saving over a built-in skill needs overwrite")
r = K.save_skill("shipped_skill", "points", "Changed how-to", "New steps.", overwrite=True)
check(r["saved"].startswith(learned) and "New steps." in K.read_skill("shipped_skill"), "overwrite writes a learned copy, which wins")
check([s["layer"] for s in K.list_skills() if s["name"] == "shipped_skill"] == ["learned"], "...and the skill is listed once")
K.save_skill("my_skill", "general", "A general how-to", "Open the panel, fill it, press Apply.")
r =K.append_version_section("other_skill", "On TBC 2027 the button moved.", release="2027.00")
learned_copy = os.path.join(learned, "skills", "survey", "other_skill.skill.md")
check(r["saved"] == learned_copy and "Old steps." in K.read_skill("other_skill") and "## TBC 2027.00" in K.read_skill("other_skill"),
      "append_version_section on a built-in skill writes a learned copy with the new section")
check(K.search("button moved", ["skill"])[0]["name"] == "other_skill", "search finds the learned version")

# --- scripts ---------------------------------------------------------------------------------------------------
scripts = {s["name"]: s for s in K.list_scripts()}
check(scripts.get("shipped_script", {}).get("layer") == "built-in", "a built-in script is listed")
check(raises(lambda: K.delete_script("shipped_script"), "built in"), "a built-in script can't be retired")
r = K.save_script("shipped_script", K.build_script("shipped_script", "Better", "read", [], "result = 2"), overwrite=True)
check(r["saved"].startswith(learned) and r["script_version"] == 2 and "result = 2" in K.read_script("shipped_script"),
      "a new version of a built-in script is saved in the learned layer as version 2")
check(os.path.isfile(os.path.join(learned, "scripts", "_archive", "shipped_script.v1.py")), "...with the built-in text archived there")
r = K.delete_script("shipped_script")
check("used again" in r.get("note", "") and "result = 1" in K.read_script("shipped_script"), "retiring the learned version brings the built-in back")

# --- lessons ---------------------------------------------------------------------------------------------------
check([l["id"] for l in K.list_lessons()] == [1, 2], "built-in lessons are read")
l1 = K.add_lesson("Vertices need at least two points", "createlinestring")
check(l1["id"] == K.USER_ID_BASE + 1, "learned lessons are numbered above the built-in ones (%s)" % l1["id"])
check(K.add_lesson("shipped LESSON about vertices ", "other")["action"] == "unchanged", "a lesson the built-ins have isn't stored twice")
K.add_lesson("Use clr imports first", "import")
rel = K.lessons_relevant_to("r = run('createlinestring')\nimport clr")
check(sorted(x["id"] for x in rel) == [1, l1["id"]], "lessons surface for a command named in code (built-in command record), not for 'import'")
check(K.delete_lesson(2)["deleted"] == 2 and 2 not in [l["id"] for l in K.list_lessons()], "deleting a built-in lesson hides it")
check(K.delete_lesson(l1["id"]) and l1["id"] not in [l["id"] for l in K.list_lessons()], "deleting a learned lesson removes it")

# --- command records -------------------------------------------------------------------------------------------
check(K.get_command("createlinestring")["caption"] == "Create Linestring", "a built-in command record is read")
K.add_command_note("createlinestring", "Press Enter after the last vertex")
rec = K.get_command("createlinestring")
check(rec["caption"] == "Create Linestring" and rec["notes"][-1]["text"] == "Press Enter after the last vertex"
      and os.path.isfile(os.path.join(learned, "commands", "createlinestring.json")), "a note goes into a learned copy of the record")
K.record_command({"command": {"key": "newcommand", "caption": "New Command"}, "fields": [{"id": "a", "label": "Layer", "options": ["X"]}]})
check(K.get_command("newcommand")["fields"][0]["options"] == "project data (not recorded)", "recorded panels go to the learned layer")
check({h["key"] for h in K.search("enter last vertex", ["command"])} == {"createlinestring"}, "search reads the learned record")

# --- preferences ------------------------------------------------------------------------------------------------
check([p["id"] for p in K.list_prefs()] == [1], "built-in preferences are read")
p1 = K.add_pref("Use numeric point IDs")
check(p1["id"] == K.USER_ID_BASE + 1 and K.add_pref("use numeric point ids")["action"] == "unchanged", "add, no duplicates")
K.update_pref(1, "Shipped preference, changed by the user")
check([p["text"] for p in K.list_prefs()] == ["Shipped preference, changed by the user", "Use numeric point IDs"],
      "updating a built-in preference stores the user's version, which wins")
K.remove_pref(1)
check([p["id"] for p in K.list_prefs()] == [p1["id"]] and "Shipped" not in K.prefs_text(), "removing a built-in preference hides it")
check(snapshot(builtin) == built_before, "the built-in layer was never written")

# --- no job data in general knowledge (contract: no job data in any repository) --------------------------------
P.link("Elm Street Drainage", os.path.join(work, "jobs", "Elm Street"), None)
lessons_before = len(K.list_lessons())
refused = lambda fn: raises(fn, "tbc_project_notes action=add")
check(refused(lambda: K.add_lesson("Imported the points from P:\\Jobs\\1234 Elm St\\Survey", "import")), "a lesson with a project-drive path is refused")
check(refused(lambda: K.add_lesson("Points went in from \\\\fileserver\\jobs\\x", "import")), "a lesson with a network path is refused")
check(K.add_lesson("Geoid files are read from C:\\ProgramData\\Trimble\\GeoData", "geoidsubgrid").get("id"), "C:\\ProgramData\\Trimble\\GeoData is allowed")
check(K.add_lesson("Macros are installed under C:/Program Files/Trimble/Trimble Business Center", "install").get("id"), "C:\\Program Files paths are allowed")
check(refused(lambda: K.add_lesson("On ELM STREET DRAINAGE the codes are separated by commas", "codes")), "a lesson naming a job (from its database) is refused")
check(refused(lambda: K.add_lesson("elm-street-drainage uses US feet", "units")), "a job's slug is refused")
check(refused(lambda: K.add_lesson("The Elm Street folder has two surfaces", "surfaces")), "the name of a job's linked folder is refused")
check(refused(lambda: K.add_lesson("Open Elm.vce before importing", "import")), "a TBC project file name is refused")
check(refused(lambda: K.add_lesson("CP.job holds the control", "import")) and refused(lambda: K.add_lesson("Use field-1.JXL", "import")),
      "job file names (.job, .jxl) are refused")
check(K.add_lesson("Import .job and *.jxl files with Home > Import; Trimble.Vce.Core holds Project", "import").get("id"),
      "a file extension alone, or the SDK namespace Trimble.Vce, is fine")
P.add_private("s3cr3t-token-9f", "the bridge's session token")
check(refused(lambda: K.add_lesson("The bridge answered with s3cr3t-token-9F", "bridge")), "a registered private value is refused")
check(refused(lambda: K.add_lesson("Logs are in %s\\TBC-MCP" % os.path.expanduser("~"), "logs")), "a user-profile path is refused")
check(refused(lambda: K.add_pref("For Elm Street Drainage always use the CTRL layer")), "a preference naming the job is refused")
check(refused(lambda: K.update_pref(p1["id"], "Use numeric point IDs on Elm Street Drainage")) and K.list_prefs()[0]["text"] == "Use numeric point IDs",
      "updating a preference to name the job is refused, the old text stays")
check(refused(lambda: K.save_skill("elm_points", "points", "Points for Elm Street Drainage", "steps")), "a skill naming the job is refused")
check(refused(lambda: K.append_version_section("my_skill", "On TBC 2027 see P:\\Jobs\\x first")), "append_version_section is guarded")
check(refused(lambda: K.add_command_note("createpoint", "Elm.vce needs the Feature code box")), "a command note with a project file is refused")
check(refused(lambda: K.save_script("s1", K.build_script("s1", "", "read", [], "path = r'P:\\Jobs\\1234\\a.csv'"))), "a script with a project path is refused")
check(len(K.list_lessons()) == lessons_before + 3 and not os.path.exists(os.path.join(learned, "skills", "points", "elm_points.skill.md")),
      "refused entries were not written")
with open(os.path.join(shared, "projects", "generic-folders.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "Generic Folders", "folders": [os.path.join(work, "jobs", "Generic", "Survey")], "notes": []}, f)
check(K.add_lesson("Survey tab tools need a licensed Survey module", "survey").get("id"), "generic folder names (Survey) don't block lessons")
saved_shared = os.environ["CIVIL3D_KNOWLEDGE_DIR"]
os.environ["CIVIL3D_KNOWLEDGE_DIR"] = os.path.join(work, "no such folder", "shared")
try:
    check(K.add_lesson("Compute Project must finish before reading results", "compute").get("id"), "a missing shared folder doesn't break saving")
finally:
    os.environ["CIVIL3D_KNOWLEDGE_DIR"] = saved_shared
check(not os.path.exists(os.path.join(work, "no such folder")), "...and isn't created by the check")

# --- the real built-ins load ------------------------------------------------------------------------------------
K.BUILTIN_ROOT = os.path.join(repo, "knowledge")
real = {s["name"]: s for s in K.list_skills()}
check(real.get("working_safely_in_tbc", {}).get("layer") == "built-in", "the repository's skills are the built-in layer")
check(len([l for l in K.list_lessons() if l["id"] < K.USER_ID_BASE]) >= 50 and K.get_command("addpoint"), "...and its lessons and command records")

# --- a whole session of writes leaves the repository untouched --------------------------------------------------
# Only CIVIL3D_KNOWLEDGE_DIR is set (as for a user): the learned layer is then <shared>\tbc
session_shared = os.path.join(work, "session_shared")
script = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
import knowledge as K, projects as P, practices as PR
assert K.USER_ROOT == os.path.join(os.environ["CIVIL3D_KNOWLEDGE_DIR"], "tbc"), K.USER_ROOT
K.add_lesson("A general lesson from the session", "createlinestring")
K.delete_lesson([l for l in K.list_lessons() if l["id"] < K.USER_ID_BASE][0]["id"])
K.add_pref("A general preference from the session")
K.update_pref(K.list_prefs()[0]["id"], "A changed built-in preference")
K.save_skill("working_safely_in_tbc", "basics", "Changed", "Changed steps.", overwrite=True)
K.append_version_section("working_safely_in_tbc", "Release notes for a later TBC.", release="2099.10")
name = K.list_scripts()[0]["name"]
K.save_script(name, K.build_script(name, "Changed", "read", [], "result = 3"), overwrite=True)
K.delete_script(name)
K.add_command_note("addpoint", "A note from the session")
K.record_command({"command": {"key": "addpoint", "caption": "Add Point"}, "fields": [], "buttons": []})
PR.add("A practice from the session")
P.link("Session Job", os.path.join(os.environ["CIVIL3D_KNOWLEDGE_DIR"], "..", "jobs", "Session"), None)
P.add_note("A fact from the session", "Session Job", None)
print("done")
'''
env = dict(os.environ, CIVIL3D_KNOWLEDGE_DIR=session_shared, PYTHONDONTWRITEBYTECODE="1",
           TBC_MCP_INFO=os.path.join(work, "no_bridge.json"), TBC_MCP_EXIT_WITH_TBC="0")
env.pop("TBC_MCP_KNOWLEDGE_DIR")
status = lambda: subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo, capture_output=True, text=True).stdout
repo_before, kb_before = status(), snapshot(os.path.join(repo, "knowledge"))
r = subprocess.run([sys.executable, "-c", script, os.path.join(repo, "mcp_server")], env=env, capture_output=True, text=True)
check(r.returncode == 0 and "done" in r.stdout, "every writer ran in a session without TBC_MCP_KNOWLEDGE_DIR%s" % (": " + r.stderr[-600:] if r.returncode else ""))
p = subprocess.Popen([sys.executable, server], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                     text=True, encoding="utf-8")
for i, (tool, args) in enumerate([("tbc_memory", {"action": "add", "text": "A lesson over MCP", "command": "addpoint"}),
                                  ("tbc_preferences", {"action": "add", "text": "A preference over MCP"}),
                                  ("tbc_practices", {"action": "add", "text": "A practice over MCP"})], 1):
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": tool, "arguments": args}}) + "\n")
    p.stdin.flush()
    answer = json.loads(p.stdout.readline())["result"]
    check(not answer["isError"], "%s add over MCP works%s" % (tool, ": " + answer["content"][0]["text"] if answer["isError"] else ""))
p.stdin.close()
p.wait(timeout=10)
learned_session = os.path.join(session_shared, "tbc")
check(os.path.isfile(os.path.join(learned_session, "memory", "lessons.jsonl")) and os.path.isfile(os.path.join(learned_session, "preferences.json"))
      and os.path.isfile(os.path.join(learned_session, "skills", "basics", "working_safely_in_tbc.skill.md"))
      and os.path.isdir(os.path.join(learned_session, "scripts", "_archive")) and os.path.isfile(os.path.join(learned_session, "commands", "addpoint.json")),
      "everything learned went to <shared>\\tbc")
check(os.path.isfile(os.path.join(session_shared, "practices.json")) and os.path.isfile(os.path.join(session_shared, "projects", "session-job.db")),
      "practices and the project database went to the shared folder")
check(status() == repo_before, "git status of the repository is unchanged")
check(snapshot(os.path.join(repo, "knowledge")) == kb_before, "no file under the repository's knowledge\\ was added or changed")

shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if ok else 1)
