# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
TBC MCP's software know-how: how to drive TBC (modelled on civil3d-mcp-unified's skills + saved scripts, plus a
memory of lessons learned and auto-recorded command panel layouts).

Two layers, with the same layout:
  BUILT-IN  <repo>\\knowledge\\           shipped with TBC MCP (and its release zip); READ ONLY at runtime
  LEARNED   TBC_MCP_KNOWLEDGE_DIR, else  everything written while working on this PC; never inside the repository
            <shared>\\tbc\\              (it reaches GitHub), so what one user learns stays on their PC
  skills/<category>/<name>.skill.md   documented how-tos with frontmatter
  scripts/<name>.py                   saved IronPython scripts with a JSON metadata header; old versions in _archive/
  memory/lessons.jsonl                one lesson per line: {id, ts, topic, tags, text, tbc_version}
  commands/<key>.json                 TBC command panel layouts seen by command_ui_*, plus notes
  preferences.json                    the user's standing rules
  memory/tbc_errors.log               TBC error popups (written by the server), crash notes
Reads merge both layers and the learned version wins: a skill or script of the same name, a command record of the
same key, a lesson or preference of the same id (a learned entry {"id": N, "retired": ...} hides built-in N). Learned
lessons and preferences get ids from USER_ID_BASE + 1 up, so they never collide with built-in ones.

<shared> is the suite's shared folder (shared_dir: PROJECT_KNOWLEDGE_DIR, else Documents\\Project Knowledge or an
earlier folder, the same rule as Civil 3D MCP and Project Analyzer; the suite contract is project-analyzer's docs/suite-knowledge.md).
Three kinds of knowledge, three places: how to drive TBC -> here; facts about one job -> the project database
(projects.py); engineering practice true on every job -> <shared>\\practices.json (practices.py).

Everything here is GENERAL TBC knowledge, useful on any job, so every writer runs check_general (the job-data guard).
Same rules as the other tools: add, never delete; small one-line entries with ids; duplicate check on add; atomic
writes; lessons surface by topic.

TBC VERSIONS: everything here records the TBC release it was verified on (baseline: 2026.10, build 44.0.9666).
When a newer TBC behaves differently, knowledge is ADDED for that release and never deleted:
  - skills: frontmatter tbc_versions + a '## TBC <release>' section appended (append_version_section)
  - lessons: new lessons carry the current release; old ones stay
  - command layouts: a different release's layout goes under 'versions' -> {release: layout}; the original stays
  - scripts: script_version increments on every save; the previous file is archived in scripts/_archive/
"""
import datetime
import json
import os
import re
import time

# ---------------------------------------------------------------------------
# where: the suite's shared folder, the built-in layer (repo) and the learned layer (this PC)
# ---------------------------------------------------------------------------
FOLDER_NAME = "Project Knowledge"
# Earlier defaults, still used as they are when they exist (newest first): Civil 3D MCP's folder before the suite had
# its own name, and its folder before 2.2.0
EARLIER_FOLDER_NAMES = ("Civil3DMcp-KnowledgeBase", "Civil3DMcp")


def _documents():
    """The user's Documents folder the way Civil 3D MCP finds it (<home>\\Documents, not a redirected shell folder),
    so every tool agrees on the default shared folder."""
    return os.path.join(os.path.expanduser("~"), "Documents")


def shared_dir(documents=None):
    """The suite's shared folder (contract "Where"): PROJECT_KNOWLEDGE_DIR, else CIVIL3D_KNOWLEDGE_DIR (its earlier
    name), else Documents\\Project Knowledge if it exists, else an earlier default that exists
    (Documents\\Civil3DMcp-KnowledgeBase, then Documents\\Civil3DMcp) as it is, else Documents\\Project Knowledge.
    Nothing is created, renamed or moved: a tool of an older version on the same PC would lose a moved folder.
    `documents` is for tests."""
    for variable in ("PROJECT_KNOWLEDGE_DIR", "CIVIL3D_KNOWLEDGE_DIR"):
        configured = os.environ.get(variable, "").strip()
        if configured:
            return configured
    documents = documents or _documents()
    for name in (FOLDER_NAME,) + EARLIER_FOLDER_NAMES:
        if os.path.isdir(os.path.join(documents, name)):
            return os.path.join(documents, name)
    return os.path.join(documents, FOLDER_NAME)


def shared_root():
    """The suite's shared folder (shared_dir); kept for callers."""
    return shared_dir()


# Built-in know-how, shipped in the repository: read only. A module variable, so tests can point it elsewhere.
BUILTIN_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge"))
# Learned know-how: TBC_MCP_KNOWLEDGE_DIR, else <shared>\tbc. Everything written at runtime goes here.
USER_ROOT = os.path.normpath(os.environ.get("TBC_MCP_KNOWLEDGE_DIR") or os.path.join(shared_dir(), "tbc"))
ROOT = USER_ROOT                       # older name, kept for callers
SKILLS = os.path.join(USER_ROOT, "skills")
SCRIPTS = os.path.join(USER_ROOT, "scripts")
MEMORY = os.path.join(USER_ROOT, "memory", "lessons.jsonl")
COMMANDS = os.path.join(USER_ROOT, "commands")
USER_ID_BASE = 100000                  # learned lessons and preferences are numbered from 100001

NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")
SCRIPT_HEADER = "tbc-script"
ARCHIVE = os.path.join(SCRIPTS, "_archive")


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _layers(*parts):
    """[learned path, built-in path] of a knowledge sub-path, the learned one first (just one when both layers are
    the same folder, e.g. TBC_MCP_KNOWLEDGE_DIR pointed at the repository's knowledge folder)."""
    out = [os.path.join(USER_ROOT, *parts)]
    builtin = os.path.join(BUILTIN_ROOT, *parts)
    if not _same(builtin, out[0]):
        out.append(builtin)
    return out


def _builtin(*parts):
    """A built-in path, or None when the learned layer is the same folder (then there is nothing separate)."""
    p = os.path.join(BUILTIN_ROOT, *parts)
    return None if _same(p, os.path.join(USER_ROOT, *parts)) else p


def is_learned(path):
    """True when a file is in the learned layer (this PC), False for a built-in one."""
    root = os.path.normcase(os.path.abspath(USER_ROOT))
    return os.path.normcase(os.path.abspath(path)).startswith(root + os.sep)


def _layer_name(path):
    return "learned" if is_learned(path) else "built-in"


# ---------------------------------------------------------------------------
# TBC version the knowledge applies to
# ---------------------------------------------------------------------------
BASELINE_RELEASE = "2026.10"            # everything written before versioning was verified on this release
BASELINE_BUILD = "44.0.9666.28609"
_tbc = {"release": None, "build": None}  # set by the server once it has asked TBC (set_tbc_version)

VERSION_RULE = ("Verified on TBC %s. If something here does not work on a newer TBC release, ADD a section "
                "'## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or "
                "rewrite the %s information.")


def set_tbc_version(release, build=None):
    """Record the running TBC release and build (the server calls this from tbc_version() once it has asked TBC).
    New knowledge is stamped with it."""
    _tbc["release"], _tbc["build"] = release, build


def current_release():
    """The TBC release new knowledge is stamped with: the running one once the server has asked TBC, else the
    baseline (2026.10)."""
    return _tbc["release"] or BASELINE_RELEASE


def version_note(versions):
    """Warning for knowledge verified on other releases than the running TBC, else None."""
    versions = versions or [BASELINE_RELEASE]
    cur = _tbc["release"]
    if cur and cur not in versions:
        return ("Verified on TBC %s; this TBC is %s. Check it still works; if not, ADD a '## TBC %s' section "
                "(do not delete the old one)." % (", ".join(versions), cur, cur))
    return None


class KnowledgeError(Exception):
    """A knowledge-base request that can't be done: bad input, not found, or refused by a rule. The server returns
    the message to the AI as a tool error, so messages say what to do instead."""
    pass


def _now():
    """Local time, ISO 8601 to the second: the timestamp of general knowledge (lessons, preferences, skills,
    scripts). Shared project notes use UTC in toISOString form instead (projects._now)."""
    return datetime.datetime.now().isoformat(timespec="seconds")


def _check_name(name, what="name"):
    """Raise KnowledgeError unless the value is 1-80 letters, digits, '_' or '-'. Used for skill and script names
    and categories, which become file and folder names."""
    if not name or not NAME_RE.match(name):
        raise KnowledgeError("%s must be 1-80 chars of letters, digits, '_' or '-': %r" % (what, name))


def _write(path, text):
    """Write a knowledge file atomically: a uniquely named temp file in the same folder, then os.replace over the
    target, so a crash (or a second server writing at the same time) never leaves half a file. UTF-8, LF line
    endings."""
    shared_root()  # the learned layer is usually inside the shared folder: move the pre-2.2.0 folder first
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # unique temp name: two AI chats (two servers) can write the same knowledge folder at once
    tmp = os.path.join(os.path.dirname(path), ".%s.%d.%d.tmp" % (os.path.basename(path), os.getpid(), int(time.time() * 1000)))
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def _read(path):
    """Read a knowledge file as text (tolerates a UTF-8 BOM)."""
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def _tokens(s):
    """Lowercase search tokens: runs of letters/digits, 2 or more characters long."""
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) > 1]


def _score(query, *texts):
    """Search relevance of the texts for a query: how often each query token occurs, plus 10 per token when every
    token occurs. 0 means no match."""
    q = _tokens(query)
    if not q:
        return 0
    hay = " ".join(t or "" for t in texts).lower()
    score = sum(hay.count(t) for t in q)
    if all(t in hay for t in q):
        score += 10 * len(q)
    return score


# ---------------------------------------------------------------------------
# no job data in general knowledge (suite contract, rule 8: no job data in any tool's repository)
# ---------------------------------------------------------------------------
# Know-how is general: the built-in layer is committed with the repository, and learned know-how may be shared or
# promoted into it, so nothing written here may name a job, its folders or files, a project drive or the user's
# profile. Job facts belong in the project database (projects.py, outside the repo).
ALLOWED_PATH_PREFIXES = ("c:\\program files", "c:\\program files (x86)", "c:\\programdata", "c:\\windows")
# Folder names too generic to identify a job, even when a job's linked folder ends in one
GENERIC_FOLDER_NAMES = {"survey", "surveys", "project", "projects", "jobs", "job", "drawings", "drawing", "documents",
                        "docs", "data", "field", "fielddata", "office", "design", "files", "export", "exports",
                        "import", "imports", "current", "archive", "working", "work", "civil", "civil3d", "trimble",
                        "plans", "sheets", "images", "photos", "control", "base", "final", "draft", "incoming",
                        "outgoing", "submittals", "correspondence", "email", "reports", "models", "points"}
_DRIVE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\")
_UNC_PATH = re.compile(r"(?:^|[\s\"'(=\[,`])\\\\[A-Za-z0-9._-]+\\[A-Za-z0-9$._-]")
_JOB_FILE = re.compile(r"[^\s\\/:*?\"'<>|`]*[A-Za-z0-9_\-)]\.(?:vce|job|jxl)\b", re.I)


def _job_names(root=None):
    """Names that identify a job in the shared projects folder (project databases and old JSON notes files): each
    job's name, its slug, and the last folder name of its analysed folder and of each linked folder (4+ characters,
    generic folder names left out). Empty when the folder is missing or unreadable - never raises, never writes.
    root: a shared folder to read instead of the configured one (for the repo audit)."""
    try:
        import projects  # imported here: projects.py imports this module
        names = set()
        for job in projects.job_index(root):
            name = str(job.get("name") or "").strip()
            folders = [f for f in job.get("roots") or [] if isinstance(f, str)]
            for n in [name, projects.slug(name), job.get("slug") or ""] + [os.path.basename(f.rstrip("\\/")) for f in folders]:
                n = n.strip()
                if len(n) >= 4 and n.lower() not in GENERIC_FOLDER_NAMES:
                    names.add(n)
        return names
    except Exception:
        return set()


def job_data_problems(text, job_names=None):
    """Why this text would put job data into general knowledge; an empty list means it is general. job_names: the
    names to look for (default: the jobs in the shared projects folder)."""
    if not text:
        return []
    problems = []
    flat = text.replace("/", "\\")
    low = re.sub(r"\\{2,}", r"\\", flat).lower()  # escaped backslashes in code/JSON count as one
    for m in _DRIVE_PATH.finditer(low):
        rest = low[m.start():]
        if not any(rest.startswith(p) and not rest[len(p):len(p) + 1].isalnum() for p in ALLOWED_PATH_PREFIXES):
            problems.append("an absolute path (%s...)" % rest[:40].split("\n")[0])
            break
    if _UNC_PATH.search(flat):
        problems.append("a network path (\\\\server\\share)")
    try:
        import projects
        projects.check_private_text(text)
    except KnowledgeError as ex:
        problems.append("private data (%s)" % str(ex).split("must not contain ", 1)[-1].split(". ", 1)[0])
    except Exception:
        pass
    for name in sorted(_job_names() if job_names is None else job_names, key=len, reverse=True):
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", text, re.I):
            problems.append("the name of a job in the shared project notes (%s)" % name)
            break
    for m in _JOB_FILE.finditer(text):
        token = m.group(0).strip("()[]{}<>,;")
        # the TBC SDK's namespace (Trimble.Vce, Trimble.Vce.Core ...) isn't a project file
        if token.lower().endswith("trimble.vce") or re.match(r"\.[A-Za-z]", text[m.end():m.end() + 2]):
            continue
        problems.append("a TBC project or job file name (%s)" % token)
        break
    return problems


def check_general(what, *texts):
    """Refuses to save general knowledge that names a job, its folders or files, a project drive or the user's profile."""
    problems = job_data_problems("\n".join(t if isinstance(t, str) else json.dumps(t, ensure_ascii=False)
                                           for t in texts if t))
    if problems:
        raise KnowledgeError(
            "Not saved: this %s would put job data into TBC's general know-how, which holds on every job and may be "
            "shared with other users: %s. Lessons, skills, scripts, command notes and preferences must be GENERAL "
            "(useful on any job; write 'the project folder', '<project>.vce' or '<project folder>\\Survey' instead of "
            "real names and paths). Record facts about "
            "this job with tbc_project_notes action=add instead (ask the user first)." % (what, "; ".join(problems)))


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------
def parse_frontmatter(text):
    """Split a .skill.md into (frontmatter dict, markdown body). Values are parsed as JSON when they can be (lists,
    booleans, quoted strings), else kept as plain strings. A doubled opening '---' is tolerated; text without
    frontmatter returns ({}, text)."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and lines[i].strip() == "---":
        i += 1  # tolerate a doubled opening '---'
    if i == 0:
        return {}, text
    meta = {}
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip()
            try:
                meta[k.strip()] = json.loads(v)
            except ValueError:
                meta[k.strip()] = v.strip('"').strip("'")
        i += 1
    return meta, "\n".join(lines[i + 1:]).lstrip("\n")


def _skill_info(path):
    """(info, body) for one skill file. info: name, category (frontmatter, else the folder name), description,
    requires_write, verified, tbc_versions (default: the baseline release), layer (built-in or learned) and path,
    plus version_note when the running TBC isn't a release the skill was verified on."""
    meta, body = parse_frontmatter(_read(path))
    name = meta.get("name") or os.path.basename(path)[:-len(".skill.md")]
    versions = meta.get("tbc_versions") or [BASELINE_RELEASE]
    info = {"name": name, "category": meta.get("category") or os.path.basename(os.path.dirname(path)),
            "description": meta.get("description", ""), "requires_write": bool(meta.get("requires_write", False)),
            "verified": meta.get("verified"), "tbc_versions": versions, "layer": _layer_name(path), "path": path}
    note = version_note(versions)
    if note:
        info["version_note"] = note
    return info, body


def _skills():
    """[(path, info, body)] of every skill: the learned ones, then the built-in ones whose name (or file name) no
    learned skill has (the learned version wins)."""
    out, names, files = [], set(), set()
    for root in _layers("skills"):
        found = []
        for dp, _, fns in os.walk(root):
            found.extend(os.path.join(dp, fn) for fn in fns if fn.endswith(".skill.md"))
        layer = []
        for p in sorted(found):
            info, body = _skill_info(p)
            if info["name"] in names or os.path.basename(p) in files:
                continue
            layer.append((p, info, body))
        for p, info, _ in layer:
            names.add(info["name"])
            files.add(os.path.basename(p))
        out.extend(layer)
    return out


def list_skills(category=None):
    """Summaries of every skill, or of one category, without file paths: what tbc_skills action=list returns."""
    out = []
    for _, info, _ in sorted(_skills(), key=lambda s: (s[1]["category"], s[1]["name"])):
        if category and info["category"] != category:
            continue
        info.pop("path")
        out.append(info)
    return out


def _skill_path(name):
    """Path of the skill whose frontmatter name or file name is `name` (the learned one when both layers have it),
    or None."""
    for p, info, _ in _skills():
        if info["name"] == name or os.path.basename(p) == name + ".skill.md":
            return p
    return None


def read_skill(name):
    """Full text of a skill for tbc_skills action=read, with a VERSION NOTE line on top when it was verified on
    another TBC release. KnowledgeError when there's no such skill."""
    p = _skill_path(name)
    if not p:
        raise KnowledgeError("No skill named %r. Use tbc_skills action=list or search." % name)
    text = _read(p)
    info, _ = _skill_info(p)
    if info.get("version_note"):
        text = "> VERSION NOTE: " + info["version_note"] + "\n\n" + text
    return text


def save_skill(name, category, description, body, requires_write=False, parameters=None, overwrite=False):
    """Create or replace <learned>\\skills\\<category>\\<name>.skill.md, stamped with the running release
    (frontmatter tbc_versions plus a banner stating the add-never-delete rule). Replacing a built-in skill writes a
    learned one of the same name, which wins from then on; the built-in file is never touched. Refused: an existing
    skill (either layer) without overwrite=True, a skill verified on another release (use append_version_section
    instead), and text that names a job (check_general). Returns {saved, tbc_version}."""
    _check_name(name)
    _check_name(category, "category")
    if not body or not body.strip():
        raise KnowledgeError("body is required (markdown: when to use, steps/code, gotchas)")
    check_general("skill", name, category, description, body, parameters)
    existing = _skill_path(name)
    path = existing if existing and is_learned(existing) else os.path.join(SKILLS, category, name + ".skill.md")
    rel = current_release()
    if existing:
        if not overwrite:
            raise KnowledgeError("Skill %r already exists; pass overwrite=true to replace it." % name)
        old = parse_frontmatter(_read(existing))[0].get("tbc_versions") or [BASELINE_RELEASE]
        if rel not in old:
            raise KnowledgeError("Skill %r holds knowledge for TBC %s; this is TBC %s. Do not overwrite it: use "
                                 "action=append_version_section to ADD what is different on %s." % (name, ", ".join(old), rel, rel))
    fm = ["---", "name: " + name, "category: " + category, "description: " + json.dumps(description or ""),
          "requires_write: " + ("true" if requires_write else "false"),
          "parameters: " + json.dumps(parameters or []), "tbc_versions: " + json.dumps([rel]),
          "updated: " + _now(), "---", "", "> " + VERSION_RULE % (rel, rel), ""]
    _write(path, "\n".join(fm) + body.strip() + "\n")
    return {"saved": path, "tbc_version": rel}


def append_version_section(name, body, release=None):
    """ADD a '## TBC <release>' section to a skill (for a TBC release that behaves differently). Never removes the
    existing sections; records the release in the frontmatter tbc_versions. A built-in skill is copied into the
    learned layer (same category folder) with the section added; the built-in file stays as shipped."""
    p = _skill_path(name)
    if not p:
        raise KnowledgeError("No skill named %r" % name)
    target = p if is_learned(p) else os.path.join(SKILLS, os.path.relpath(p, os.path.join(BUILTIN_ROOT, "skills")))
    if not body or not body.strip():
        raise KnowledgeError("body is required: what is different on this release")
    check_general("skill section", body)
    rel = release or current_release()
    text = _read(p)
    meta, _ = parse_frontmatter(text)
    versions = meta.get("tbc_versions") or [BASELINE_RELEASE]
    if rel not in versions:
        versions = versions + [rel]
        if re.search(r"^tbc_versions:.*$", text, re.M):
            text = re.sub(r"^tbc_versions:.*$", "tbc_versions: " + json.dumps(versions), text, count=1, flags=re.M)
        else:
            text = re.sub(r"^(name: .*)$", r"\1\ntbc_versions: " + json.dumps(versions).replace("\\", "\\\\"), text, count=1, flags=re.M)
    text = text.rstrip("\n") + "\n\n## TBC %s (added %s)\n\n%s\n" % (rel, _now()[:10], body.strip())
    _write(target, text)
    return {"appended": "TBC " + rel, "skill": name, "tbc_versions": versions, "saved": target}


# ---------------------------------------------------------------------------
# scripts
# ---------------------------------------------------------------------------
def parse_script(text):
    """Split a saved script into (metadata dict, code). The metadata is the JSON inside the leading docstring that
    starts with 'tbc-script'; KnowledgeError when that header is missing or isn't valid JSON."""
    m = re.match(r'\s*(?:"""|\'\'\')\s*' + SCRIPT_HEADER + r'\s*\n(.*?)(?:"""|\'\'\')', text, re.S)
    if not m:
        raise KnowledgeError("Script is missing its metadata header (docstring starting with '%s')" % SCRIPT_HEADER)
    try:
        meta = json.loads(m.group(1))
    except ValueError as ex:
        raise KnowledgeError("Bad JSON in script header: %s" % ex)
    return meta, text[m.end():].lstrip("\n")


def _script_path(name):
    """<learned>\\scripts\\<name>.py (where a script is saved), after checking the name is safe as a file name."""
    _check_name(name)
    return os.path.join(SCRIPTS, name + ".py")


def _script_file(name):
    """The file of a saved script: the learned one, else the built-in one, else None."""
    _check_name(name)
    return next((p for p in (os.path.join(d, name + ".py") for d in _layers("scripts")) if os.path.exists(p)), None)


def list_scripts():
    """Summary of every saved script (name, description, mode, script_version, tbc_versions, parameter names,
    layer, version_note); a learned script hides the built-in one of the same name. A script whose header can't be
    read is listed with its error instead of being hidden."""
    out, seen = [], set()
    for d in _layers("scripts"):
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py") or fn in seen:
                continue
            seen.add(fn)
            path = os.path.join(d, fn)
            try:
                meta, _ = parse_script(_read(path))
                rec = {"name": meta.get("name", fn[:-3]), "description": meta.get("description", ""),
                       "mode": meta.get("mode", "read"), "script_version": meta.get("script_version", 1),
                       "tbc_versions": meta.get("tbc_versions") or [BASELINE_RELEASE],
                       "parameters": [p.get("name") for p in meta.get("parameters", [])], "layer": _layer_name(path)}
                note = version_note(rec["tbc_versions"])
                if note:
                    rec["version_note"] = note
                out.append(rec)
            except KnowledgeError as ex:
                out.append({"name": fn[:-3], "error": str(ex), "layer": _layer_name(path)})
    return sorted(out, key=lambda s: s["name"])


def read_script(name):
    """Full text (header and code) of a saved script (the learned one when both layers have it); KnowledgeError
    when there's no such script."""
    p = _script_file(name)
    if not p:
        raise KnowledgeError("No script named %r" % name)
    return _read(p)


def build_script(name, description, mode, parameters, code):
    """Assemble a new script's text: the 'tbc-script' JSON header (name, description, mode read|write, typed
    parameters, script_version 1, the running TBC release and build, timestamp) followed by the code. Checks the
    mode and every parameter's type."""
    if mode not in ("read", "write"):
        raise KnowledgeError("mode must be 'read' or 'write'")
    for prm in parameters or []:
        if not prm.get("name") or prm.get("type") not in ("string", "number", "integer", "boolean", "array", "object"):
            raise KnowledgeError("each parameter needs a name and type (string|number|integer|boolean|array|object): %r" % prm)
    meta = {"name": name, "description": description or "", "mode": mode, "parameters": parameters or [],
            "script_version": 1, "tbc_versions": [current_release()], "tbc_build": _tbc["build"] or BASELINE_BUILD,
            "updated": _now()}
    header = '"""' + SCRIPT_HEADER + "\n" + json.dumps(meta, indent=1) + '\n"""\n'
    return header + code.strip("\n") + "\n"


def _with_meta(text, **changes):
    """The script text with some header fields replaced (save_script uses it to bump script_version and record
    releases)."""
    meta, code = parse_script(text)
    meta.update(changes)
    return '"""' + SCRIPT_HEADER + "\n" + json.dumps(meta, indent=1) + '\n"""\n' + code


def save_script(name, text, overwrite=False):
    """Save a script. Versioning: script_version starts at 1 and goes up by one on every overwrite; the previous
    file is kept as scripts/_archive/<name>.v<N>.py (never deleted). tbc_versions lists the TBC releases the
    script was saved/tested on: saving on a new release adds that release, the old ones stay listed. Always saved
    in the learned layer; a new version of a built-in script archives the built-in text there and wins from then
    on (the built-in file is never touched)."""
    p = _script_path(name)
    meta, _ = parse_script(text)
    check_general("script", text)
    existing = _script_file(name)
    if existing:
        if not overwrite:
            raise KnowledgeError("Script %r already exists; pass overwrite=true to save a new version of it." % name)
        old_text = _read(existing)
        old = parse_script(old_text)[0]
        n = int(old.get("script_version", 1))
        _write(os.path.join(ARCHIVE, "%s.v%d.py" % (name, n)), old_text)
        versions = list(old.get("tbc_versions") or [BASELINE_RELEASE])
        if current_release() not in versions:
            versions.append(current_release())
        text = _with_meta(text, script_version=n + 1, tbc_versions=versions, previous_version_archived="_archive/%s.v%d.py" % (name, n))
    else:
        text = _with_meta(text, script_version=meta.get("script_version", 1),
                          tbc_versions=meta.get("tbc_versions") or [current_release()])
    _write(p, text)
    return {"saved": p, "script_version": parse_script(text)[0]["script_version"]}


def delete_script(name):
    """Retire a learned script: it is moved to scripts/_archive (kept for older TBC releases), not destroyed. A
    built-in script ships with TBC MCP and is refused (save a new version instead); when a learned script hid a
    built-in one, the built-in one is used again."""
    p = _script_path(name)
    if not os.path.exists(p):
        if _script_file(name):
            raise KnowledgeError("Script %r is built in (shipped with TBC MCP), so it can't be retired here. Save a new "
                                 "version of it instead (tbc_script save overwrite=true)." % name)
        raise KnowledgeError("No script named %r" % name)
    text = _read(p)
    n = int(parse_script(text)[0].get("script_version", 1))
    _write(os.path.join(ARCHIVE, "%s.v%d.retired.py" % (name, n)), text)
    os.remove(p)
    r = {"retired": name, "archived_as": "_archive/%s.v%d.retired.py" % (name, n)}
    if _script_file(name):
        r["note"] = "The built-in script of the same name is used again."
    return r


def bind_args(meta, given):
    """Validate/coerce run arguments against the script's declared parameters."""
    given = dict(given or {})
    out = {}
    conv = {"number": float, "integer": int, "string": str}
    for prm in meta.get("parameters", []):
        n = prm["name"]
        if n in given:
            v = given.pop(n)
            t = prm.get("type")
            try:
                if t in conv and v is not None:
                    v = conv[t](v)
                elif t == "boolean" and isinstance(v, str):
                    v = v.strip().lower() in ("1", "true", "yes", "on")
            except (TypeError, ValueError):
                raise KnowledgeError("parameter %r should be %s, got %r" % (n, t, v))
            out[n] = v
        elif "default" in prm:
            out[n] = prm["default"]
        elif prm.get("required"):
            raise KnowledgeError("missing required parameter %r (%s)" % (n, prm.get("description", "")))
    if given:
        raise KnowledgeError("unknown parameter(s) %s; declared: %s" % (sorted(given), [p["name"] for p in meta.get("parameters", [])]))
    return out


# ---------------------------------------------------------------------------
# memory (lessons learned)
# ---------------------------------------------------------------------------
def _read_jsonl(path):
    """The JSON objects of a .jsonl file, one per line ([] when it is missing). Blank or unreadable lines are
    skipped."""
    if not path or not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    return out


def _merge_by_id(builtin, learned):
    """Built-in entries, then learned ones: a learned entry with a built-in id replaces it (in place), and one with
    'retired' set hides it. Retired entries are left out."""
    merged, order = {}, []
    for rec in list(builtin) + list(learned):
        key = rec.get("id")
        if key not in merged:
            order.append(key)
        merged[key] = rec
    return [merged[k] for k in order if not merged[k].get("retired")]


def _lessons():
    """Every current lesson: the built-in memory\\lessons.jsonl merged with the learned one."""
    return _merge_by_id(_read_jsonl(_builtin("memory", "lessons.jsonl")), _read_jsonl(MEMORY))


def _next_user_id(entries):
    """The next id for a learned lesson or preference: above USER_ID_BASE and above every learned id."""
    return max([USER_ID_BASE] + [e.get("id") for e in entries if isinstance(e.get("id"), int)]) + 1


def add_lesson(text, topic=None, tags=None):
    """Append a lesson {id, ts, topic, tags, text, tbc_version} to memory\\lessons.jsonl. The topic is lowercased
    ('general' by default); when it is a command key the lesson is shown whenever that command's panel opens
    (remembered_for_command) and when code names the command (lessons_relevant_to). The same text, in any case,
    is never stored twice: the existing lesson comes back with action='unchanged'. Text that names a job is
    refused (check_general)."""
    if not text or not text.strip():
        raise KnowledgeError("text is required")
    check_general("lesson", text, topic, tags)
    ls = _lessons()
    duplicate = next((l for l in ls if l.get("text", "").strip().lower() == text.strip().lower()), None)
    if duplicate:
        return dict(duplicate, action="unchanged", note="That lesson is already recorded.")
    lid = _next_user_id(_read_jsonl(MEMORY))
    rec = {"id": lid, "ts": _now(), "topic": (topic or "general").strip().lower(), "tags": tags or [], "text": text.strip(),
           "tbc_version": current_release()}
    shared_root()  # the learned layer is usually inside the shared folder: move the pre-2.2.0 folder first
    os.makedirs(os.path.dirname(MEMORY), exist_ok=True)
    with open(MEMORY, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def list_lessons(topic=None):
    """Every lesson, or only those with this topic."""
    ls = _lessons()
    if topic:
        ls = [l for l in ls if l.get("topic") == topic.strip().lower()]
    return ls


def lessons_relevant_to(text, limit=6):
    """Lessons about a TBC command named in the given text (e.g. code about to run in TBC), so known pitfalls
    surface where they matter (as civil3d-mcp-unified does with its lessons' topics). Only topics that are command
    keys count: broad topics and tags (import, all, survey ...) would match almost any code."""
    words = set(re.findall(r"[a-z0-9_]+", (text or "").lower()))
    out = []
    for l in _lessons():
        topic = (l.get("topic") or "").lower()
        if topic in words and _cmd_file(topic):
            rec = {"id": l["id"], "topic": l.get("topic"), "text": l["text"], "tbc_version": l.get("tbc_version", BASELINE_RELEASE)}
            if rec["tbc_version"] != current_release():
                rec["version_note"] = "Learned on TBC %s; this TBC is %s. Check it still applies." % (rec["tbc_version"], current_release())
            out.append(rec)
            if len(out) >= limit:
                break
    return out


def delete_lesson(lid):
    """Delete a lesson that turned out to be WRONG on its own release. A lesson recorded on another TBC release is
    never deleted (it is still true there): add a new lesson for the current release instead. A learned lesson is
    removed from the learned file; a built-in one is hidden by a learned {"id", "retired"} entry (the repository's
    file is never changed)."""
    lid = int(lid)
    gone = next((l for l in _lessons() if l.get("id") == lid), None)
    if not gone:
        raise KnowledgeError("No lesson with id %s" % lid)
    if gone.get("tbc_version", BASELINE_RELEASE) != current_release():
        raise KnowledgeError("Lesson %s was recorded on TBC %s (this is %s). Keep it; add a lesson for %s with what "
                             "is different." % (lid, gone.get("tbc_version", BASELINE_RELEASE), current_release(), current_release()))
    keep = [l for l in _read_jsonl(MEMORY) if l.get("id") != lid]
    if any(l.get("id") == lid for l in _read_jsonl(_builtin("memory", "lessons.jsonl"))):
        keep.append({"id": lid, "retired": _now()})
    _write(MEMORY, "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in keep))
    return {"deleted": lid}


# ---------------------------------------------------------------------------
# remembered command panels
# ---------------------------------------------------------------------------
def _cmd_name(key):
    """<key>.json for a TBC command key (lowercased; characters unsafe in file names replaced by '_')."""
    return re.sub(r"[^A-Za-z0-9_\-.]", "_", key.lower()) + ".json"


def _cmd_path(key):
    """<learned>\\commands\\<key>.json: where a command's record is written."""
    return os.path.join(COMMANDS, _cmd_name(key))


def _cmd_file(key):
    """The file of a command's record: the learned one, else the built-in one, else None."""
    return next((p for p in (os.path.join(d, _cmd_name(key)) for d in _layers("commands")) if os.path.exists(p)), None)


def get_command(key):
    """The remembered panel layout and notes of a command (the learned record when both layers have one), or None
    when there are none or the file can't be read."""
    p = _cmd_file(key)
    if p:
        try:
            return json.loads(_read(p))
        except ValueError:
            return None
    return None


# Dropdowns whose entries come from the user's project (layer, surface, style, block names, folders ...): their
# options are NOT recorded - they are project data and must not end up in a shared knowledge base.
PROJECT_LIST_RE = re.compile(r"layer|surface|style|block|folder|plan ?set|sheet ?set|feature|template|corridor|"
                             r"alignment|boundary|library|font|recent|path|file|profile|point ?id|name|attr|code|"
                             r"selection|source|target|lyr|filter|cbo(?:Attr|Field)", re.I)


def _project_list(f):
    """True when a dropdown's entries are project data (layers, surfaces, styles, names ...) judging by its label
    and id, or when it has no label: such options are never recorded in the shared knowledge base."""
    if not (f.get("label") or "").strip():
        return True  # unlabelled dropdown: purpose unknown, so treat its entries as project data
    return bool(PROJECT_LIST_RE.search("%s %s" % (f.get("id") or "", f.get("label") or "")))


def record_command(state):
    """Store the field/button layout of a command panel (keeps existing notes). Options of project-data dropdowns
    (layers, surfaces, styles ...) are not stored, so no project or user data reaches the knowledge base."""
    c = state.get("command")
    if not c:
        return None
    old = get_command(c["key"]) or {}
    fields = []
    for f in state.get("fields", []):
        d = {"id": f.get("id"), "label": f.get("label"), "kind": f.get("kind")}
        if f.get("options"):
            if _project_list(f):
                d["options"] = "project data (not recorded)"
            else:
                d["options_sample"] = f["options"][:8]
                d["option_count"] = len(f["options"])
        fields.append(d)
    layout = {"caption": c.get("caption"), "last_seen": _now(), "fields": fields,
              "buttons": [b.get("text") for b in state.get("buttons", [])]}
    rel = current_release()
    if old and old.get("tbc_version", BASELINE_RELEASE) != rel:
        # a different TBC release: keep the original layout, add this release's next to it
        rec = old
        rec.setdefault("versions", {})[rel] = layout
    else:
        rec = dict(layout, key=c["key"], tbc_version=rel, notes=old.get("notes", []))
        if old.get("versions"):
            rec["versions"] = old["versions"]
    _write(_cmd_path(c["key"]), json.dumps(rec, indent=1, ensure_ascii=False))
    return rec


def add_command_note(key, text):
    """Attach a note to a command's record (created if needed), stamped with the running release; it is shown the
    next time that command is opened. Text that names a job is refused (check_general)."""
    check_general("command note", key, text)
    rec = get_command(key) or {"key": key, "fields": [], "buttons": [], "notes": []}
    rec.setdefault("notes", []).append({"ts": _now(), "text": text.strip(), "tbc_version": current_release()})
    _write(_cmd_path(key), json.dumps(rec, indent=1, ensure_ascii=False))
    return rec


def remembered_for_command(key):
    """What to show the AI when a command's panel opens: the command's notes and the lessons whose topic is the
    command key, each prefixed [TBC <release>] when it comes from another release. None when there is nothing."""
    rec = get_command(key) or {}
    tag = lambda v: "" if (v or BASELINE_RELEASE) == current_release() else "[TBC %s] " % (v or BASELINE_RELEASE)
    lessons = [tag(l.get("tbc_version")) + l["text"] for l in list_lessons(key.lower())]
    notes = [tag(n.get("tbc_version")) + n["text"] for n in rec.get("notes", [])]
    return {"notes": notes + lessons} if (notes or lessons) else None


# ---------------------------------------------------------------------------
# user preferences (standing rules; injected into the server instructions for every AI)
# ---------------------------------------------------------------------------
PREFS = os.path.join(USER_ROOT, "preferences.json")  # the learned preferences (written here)


def _read_prefs(path):
    """A preferences.json (a JSON list of {id, topic, text, added, updated?}); [] when it is missing or unreadable."""
    if not path or not os.path.exists(path):
        return []
    try:
        data = json.loads(_read(path))
    except ValueError:
        return []
    return [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []


def list_prefs():
    """The user's preferences: the built-in preferences.json merged with the learned one (a learned entry with a
    built-in id replaces it; one with 'retired' hides it)."""
    return _merge_by_id(_read_prefs(_builtin("preferences.json")), _read_prefs(PREFS))


def add_pref(text, topic=None):
    """Add a standing rule from the user (to the learned preferences). The same text, in any case, returns the
    existing preference (action='unchanged'); text that names a job is refused (check_general)."""
    if not text or not text.strip():
        raise KnowledgeError("text is required")
    check_general("preference", text, topic)
    duplicate = next((p for p in list_prefs() if p.get("text", "").strip().lower() == text.strip().lower()), None)
    if duplicate:
        return dict(duplicate, action="unchanged", note="That preference already exists.")
    learned = _read_prefs(PREFS)
    rec = {"id": _next_user_id(learned), "topic": (topic or "general").strip().lower(), "text": text.strip(), "added": _now()}
    learned.append(rec)
    _write(PREFS, json.dumps(learned, indent=1, ensure_ascii=False))
    return rec


def update_pref(pid, text):
    """Replace a preference's text and stamp 'updated'. A built-in preference gets a learned copy with the new text
    (same id), which wins. Text that names a job is refused; KnowledgeError for an unknown id."""
    check_general("preference", text)
    pid = int(pid)
    current = next((p for p in list_prefs() if p.get("id") == pid), None)
    if not current:
        raise KnowledgeError("No preference with id %s" % pid)
    learned = _read_prefs(PREFS)
    entry = next((p for p in learned if p.get("id") == pid), None)
    if entry is None:
        entry = dict(current)
        learned.append(entry)
    entry["text"] = text.strip()
    entry["updated"] = _now()
    _write(PREFS, json.dumps(learned, indent=1, ensure_ascii=False))
    return entry


def remove_pref(pid):
    """Remove a preference the user has retracted: a learned one is deleted, a built-in one is hidden by a learned
    {"id", "retired"} entry. KnowledgeError for an unknown id."""
    pid = int(pid)
    if not any(p.get("id") == pid for p in list_prefs()):
        raise KnowledgeError("No preference with id %s" % pid)
    keep = [p for p in _read_prefs(PREFS) if p.get("id") != pid]
    if any(p.get("id") == pid for p in _read_prefs(_builtin("preferences.json"))):
        keep.append({"id": pid, "retired": _now()})
    _write(PREFS, json.dumps(keep, indent=1, ensure_ascii=False))
    return {"removed": pid}


def prefs_text():
    """The preferences as the block the server appends to its MCP instructions, so every AI in every chat follows
    them; '' when there are none."""
    ps = list_prefs()
    if not ps:
        return ""
    return "USER PREFERENCES (standing rules from the user - always follow them):\n" + "\n".join(
        "- [%s] %s" % (p.get("topic", "general"), p.get("text", "")) for p in ps)


# ---------------------------------------------------------------------------
# unified search
# ---------------------------------------------------------------------------
def search(query, kinds=None, limit=15):
    """One ranked search across skills, saved scripts, lessons and remembered command panels (`kinds` picks which),
    used by tbc_skills action=search and tbc_memory action=search. Each hit says its type and the TBC release(s)
    it was verified on; at most `limit` hits."""
    kinds = kinds or ["skill", "script", "lesson", "command"]
    hits = []
    if "skill" in kinds:
        for p, info, body in _skills():
            s = _score(query, info["name"], info["name"], info["description"], info["category"], body)
            if s:
                h = {"type": "skill", "name": info["name"], "category": info["category"],
                     "description": info["description"], "tbc_versions": info["tbc_versions"]}
                if info.get("version_note"):
                    h["version_note"] = info["version_note"]
                hits.append((s, h))
    if "script" in kinds:
        for sc in list_scripts():
            s = _score(query, sc["name"], sc["name"], sc.get("description", ""))
            if s:
                hits.append((s, dict(sc, type="script")))
    if "lesson" in kinds:
        for l in _lessons():
            s = _score(query, l.get("topic"), l.get("text"), " ".join(l.get("tags", [])))
            if s:
                hits.append((s, {"type": "lesson", "id": l["id"], "topic": l["topic"], "text": l["text"],
                                 "tbc_version": l.get("tbc_version", BASELINE_RELEASE)}))
    if "command" in kinds:
        seen = set()
        records = []
        for d in _layers("commands"):
            for fn in (sorted(os.listdir(d)) if os.path.isdir(d) else []):
                if fn.endswith(".json") and fn not in seen:  # the learned record of a command wins
                    seen.add(fn)
                    records.append(os.path.join(d, fn))
        for path in records:
            try:
                rec = json.loads(_read(path))
            except Exception:
                continue
            if not isinstance(rec, dict) or not rec.get("key"):
                continue
            labels = " ".join((f.get("label") or "") for f in rec.get("fields", []))
            notes = " ".join(n["text"] for n in rec.get("notes", []))
            s = _score(query, rec.get("key"), rec.get("caption"), labels, notes)
            if s:
                hits.append((s, {"type": "command", "key": rec["key"], "caption": rec.get("caption"),
                                 "tbc_version": rec.get("tbc_version", BASELINE_RELEASE),
                                 "other_versions": sorted(rec.get("versions", {})),
                                 "fields": [f.get("label") or f.get("id") for f in rec.get("fields", [])][:15],
                                 "notes": [n["text"] for n in rec.get("notes", [])][-5:]}))
    hits.sort(key=lambda h: -h[0])
    return [h[1] for h in hits[:limit]]
