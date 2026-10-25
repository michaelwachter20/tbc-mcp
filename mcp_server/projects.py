# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Project knowledge shared with civil3d-mcp-unified and project-analyzer: one knowledge base per job for the whole suite.

The contract all three follow is project-analyzer's docs/shared-project-knowledge.md. In short, the three tools keep
what they learn about ONE job in the same plain files, so facts the Civil 3D assistant or Project Analyzer recorded
come back in TBC, and the other way round:

    <shared dir>\\projects\\<slug>.json   {name, folders, notes: [{id: note-N, note, added, updated?, source?}], ...}
    <shared dir>\\projects\\<slug>\\      the job's files folder: reference files the user drops in, and Project
                                         Analyzer's reports: analysis\\ (OVERVIEW.md, TIMELINE.md, PEOPLE.md,
                                         ISSUES.md, INDEX.md) and analysis\\intel\\ (ENTITIES.md, TIMELINE.md,
                                         THREADS.md, VERSIONS.md, AMOUNTS.md)

<shared dir> follows civil3d-mcp-unified's knowledgeRoot() exactly: CIVIL3D_KNOWLEDGE_DIR, else
Documents\\Civil3DMcp-KnowledgeBase (moved there from the pre-2.2.0 Documents\\Civil3DMcp once, as Civil 3D MCP does).
The slug, folder matching and file format are the same as its projectNotes.ts, so none of the other tools change.

A job is matched by folder: the open TBC project (.vce) belongs to the job with the deepest linked folder that
contains it. Rules:
  - job facts only; general TBC knowledge (lessons, skills, scripts) stays in knowledge.py and never names a job
  - each tool owns its notes: TBC updates or removes only notes with source "tbc", and unlinks only the folders it
    linked (listed in its own top-level field "tbc_linked_folders"); everything else is corrected by adding
  - the file is re-read right before every write, and fields TBC doesn't know (top level and on notes) are kept
  - one-line notes with stable ids, duplicate check on add, the suite's reference formats, atomic writes
  - privacy: no license details, session tokens or user-profile paths in notes or folders
"""
import datetime
import json
import os
import re

from knowledge import KnowledgeError

FOLDER_NAME = "Civil3DMcp-KnowledgeBase"
LEGACY_FOLDER_NAME = "Civil3DMcp"      # Civil 3D MCP's default before 2.2.0
SOURCE = "tbc"                         # marks the notes TBC wrote (the other tools keep unknown fields)
OWN_FOLDERS = "tbc_linked_folders"     # TBC's own top-level field: the folders it linked (only those can be unlinked)
MAX_READ_CHARS = 20000
ANALYSIS_REPORTS = ("OVERVIEW.md", "TIMELINE.md", "PEOPLE.md", "ISSUES.md", "INDEX.md")
INTEL_REPORTS = ("ENTITIES.md", "TIMELINE.md", "THREADS.md", "VERSIONS.md", "AMOUNTS.md")

# How every tool in the suite writes references, so Project Analyzer's automatic connections tie a note to the same
# items in documents and drawings (contract: Reference formats)
REFERENCE_FORMATS = ("dates 2026-10-03; stations 12+50 (12+50.25 only when decimals matter); structures MH-3, CB-12, "
                     "FES-1; sheets C-104; documents RFI 12, CO 4, PCO 7, Submittal 3, ASI 2, Addendum 1, Pay App 5; "
                     "amounts $12,500.00; people by full name, then initials if the files use them: John Smith (J. Smith)")
_FORMAT_CHECKS = [
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"), "write dates as 2026-10-03"),
    (re.compile(r"\bsta(?:tion)?\.?\s*\d{3,}(?:\.\d+)?\b(?!\+)", re.I), "write stations as 12+50"),
    (re.compile(r"\b(?:manhole|catch ?basin)\s*#?\s*\d+|\b(?:MH|CB|FES)\s*#\s*\d+|\b(?:MH|CB|FES)\d+\b", re.I), "write structures as MH-3, CB-12"),
    (re.compile(r"\b(?:sheet|sht\.?)\s+[A-Z]{1,3}\d{2,}\b", re.I), "write sheets as C-104"),
    (re.compile(r"\bRFI[-#\s]*0\d+|\bchange order\s*#?\s*\d+|\bCO\s*#\s*\d+", re.I), "write documents as RFI 12, CO 4"),
    (re.compile(r"\$?\b\d+(?:\.\d+)?\s*[kK]\b"), "write amounts as $12,500.00"),
]
TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".html", ".htm", ".log", ".ini",
                   ".yaml", ".yml", ".landxml", ".gsi", ".job", ".raw", ".rw5", ".fbk", ".asc", ".pts"}

# Project Analyzer's notes end "[source: <file>; fact-N]"; its first note points to the reports (analyzer/civil3d.py)
_ANALYZER_NOTE = re.compile(r"; fact-\d+\]$")
_ANALYZER_POINTER = "Full analysis of this project (overview, timeline, people, issues, index) is in this project's files"

_migration_checked = [False]


def _documents():
    return os.path.join(os.path.expanduser("~"), "Documents")


def migrate_legacy_folder(documents=None):
    """Same as Civil 3D MCP's migrateLegacyKnowledgeFolder: Documents\\Civil3DMcp -> Documents\\Civil3DMcp-KnowledgeBase,
    once, when only the old one exists. Doing it here keeps TBC from creating an empty new folder that would stop
    Civil 3D MCP from moving the user's existing knowledge."""
    documents = documents or _documents()
    legacy, current = os.path.join(documents, LEGACY_FOLDER_NAME), os.path.join(documents, FOLDER_NAME)
    if not os.path.isdir(legacy) or os.path.exists(current):
        return None
    try:
        os.rename(legacy, current)
        return "Knowledge base moved from %s to %s." % (legacy, current)
    except OSError:
        return None  # in use or not allowed: the old folder stays intact


def shared_root():
    configured = os.environ.get("CIVIL3D_KNOWLEDGE_DIR", "").strip()
    if configured:
        return configured
    documents = _documents()
    if not _migration_checked[0]:
        _migration_checked[0] = True
        migrate_legacy_folder(documents)
    return os.path.join(documents, FOLDER_NAME)


def projects_dir():
    return os.path.join(shared_root(), "projects")


def slug(name):
    """Same as projectNotes.ts: lowercase, non-alphanumerics to '-', trimmed, at most 64 characters."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")[:64]


def one_line(value):
    return re.sub(r"[\r\n]+", " ", value or "").strip()


def normalize_folder(folder):
    return os.path.abspath(folder).rstrip("\\/")


def _now():
    # Same form as JavaScript's toISOString(), which the other tools write
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _write_atomically(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = os.path.join(os.path.dirname(path), ".%s.%d.%d.tmp" % (os.path.basename(path), os.getpid(),
                                                                  int(datetime.datetime.now().timestamp() * 1000)))
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def project_file(name):
    key = slug(name)
    if not key:
        raise KnowledgeError("Give the project a name with letters or digits.")
    return os.path.join(projects_dir(), key + ".json")


def files_dir(name):
    """The project's files folder, <shared dir>\\projects\\<slug>\\ next to <slug>.json."""
    return project_file(name)[:-len(".json")]


def _load(path):
    """A job file as written by any tool. Every field is kept as it is, including ones TBC doesn't know, so _save
    writes them back unchanged (same order, same values)."""
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    data.setdefault("folders", [])
    data.setdefault("notes", [])
    return data


def _load_for_write(name):
    """Re-reads the job file right before a change (another tool may have written since), so the change is merged
    into the latest version. A file that doesn't parse is never rewritten."""
    path = project_file(name)
    if not os.path.exists(path):
        return None
    try:
        return _load(path)
    except (OSError, ValueError) as ex:
        raise KnowledgeError("%s can't be read (%s), so it isn't changed. Fix or restore it first." % (path, ex))


def _save(project):
    # json.dumps keeps every key in its original order, and indent=2 + ensure_ascii=False is the layout
    # JavaScript's JSON.stringify(project, null, 2) writes, so other tools' entries stay byte-for-byte the same
    _write_atomically(project_file(project["name"]), json.dumps(project, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# privacy: nothing private goes into the shared files (contract: Privacy)
# ---------------------------------------------------------------------------
_private = {}  # lowercased value -> what it is; registered by the server (session token, license fingerprint)


def add_private(value, what):
    """Register a value that must never reach a shared note (the bridge token, the license fingerprint ...)."""
    if value and len(str(value)) >= 6:
        _private[str(value).lower()] = what


def _private_folders():
    """Per-user folders that never belong in a shared job: the profile root itself, AppData, temp, TBC MCP's own."""
    roots = [os.environ.get(v) for v in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "TBC_MCP_USER_DIR")]
    return [normalize_folder(r).lower() for r in roots if r]


def _profile():
    return normalize_folder(os.path.expanduser("~")).lower()


def check_private_text(text):
    low = (text or "").lower().replace("/", "\\")
    found = sorted({what for value, what in _private.items() if value in low})
    if _profile() and _profile() + "\\" in low:
        found.append("a path inside your user profile (write the file name, or the path inside the job folder)")
    if found:
        raise KnowledgeError("Shared project notes must not contain %s. Notes are shared with other tools and people; "
                             "rewrite the note without it." % " or ".join(found))


def check_private_folder(folder):
    f = normalize_folder(folder).lower()
    if f == _profile() or any(f == r or f.startswith(r + "\\") for r in _private_folders()):
        raise KnowledgeError("%s is a private per-user folder (user profile, AppData or temp), so it can't be linked to "
                             "a shared job. Link the job's own folder (drawings, TBC projects, documents)." % folder)


def format_hints(text):
    """Reference-format reminders for a note (it is still saved: they're advice, not rules)."""
    return sorted({hint for rx, hint in _FORMAT_CHECKS if rx.search(text)})


def list_projects():
    d = projects_dir()
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".json"):
            try:
                out.append(_load(os.path.join(d, fn)))
            except (OSError, ValueError):
                continue  # a half-written or hand-broken file: skip it, never rewrite it
    return out


def find_project(name):
    return _load_for_write(name)


def project_for_path(path):
    """The project with the deepest linked folder that contains this file (the open .vce)."""
    if not path or not os.path.isabs(path):
        return None
    directory = normalize_folder(os.path.dirname(path)).lower()
    best, depth = None, -1
    for project in list_projects():
        for folder in project["folders"]:
            root = normalize_folder(folder).lower()
            if directory == root or directory.startswith(root + os.sep) or directory.startswith(root + "/"):
                if len(root) > depth:
                    best, depth = project, len(root)
    return best


TOOL_LABELS = {"civil3d": "Civil 3D MCP", "project-analyzer": "Project Analyzer", SOURCE: "TBC MCP"}


def origin(note):
    """Which tool wrote a note. The `source` field is trusted first ("tbc", "project-analyzer", ...). Without one, the
    note is Project Analyzer's only if it is one of its older notes (text ending "; fact-N]", or its pointer to the
    reports), which predate the field; anything else without a source is civil3d-mcp-unified's."""
    if note.get("source"):
        return str(note["source"])
    text = note.get("note", "")
    if _ANALYZER_NOTE.search(text) or text.startswith(_ANALYZER_POINTER):
        return "project-analyzer"
    return "civil3d"


def _present_notes(project):
    return [dict(n, by=origin(n)) for n in project["notes"] if isinstance(n, dict)]


def list_files(directory, limit=500):
    files, truncated = [], False
    if os.path.isdir(directory):
        for dp, dns, fns in os.walk(directory):
            dns.sort()
            for fn in sorted(fns):
                if len(files) >= limit:
                    truncated = True
                    break
                full = os.path.join(dp, fn)
                st = os.stat(full)
                files.append({"path": os.path.relpath(full, directory), "size": st.st_size,
                              "modified": datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc)
                              .isoformat(timespec="seconds").replace("+00:00", "Z")})
            if truncated:
                break
    files.sort(key=lambda f: f["path"].lower())
    return files, truncated


def _ensure_files_dir(name):
    d = files_dir(name)
    os.makedirs(d, exist_ok=True)
    return d


def _analysis_hint(directory):
    """What Project Analyzer has written for this job, and how to use it, or None."""
    analysis, intel = os.path.join(directory, "analysis"), os.path.join(directory, "analysis", "intel")
    reports = [r for r in ANALYSIS_REPORTS if os.path.isfile(os.path.join(analysis, r))]
    connections = [r for r in INTEL_REPORTS if os.path.isfile(os.path.join(intel, r))]
    if not reports and not connections:
        return None
    parts = ["Project Analyzer has analysed this job's documents (read them with tbc_project_notes action=read file=...)."]
    if reports:
        parts.append("Reports in analysis\\: %s - start with %s. Their facts cite the source files."
                     % (", ".join(reports), "OVERVIEW.md" if "OVERVIEW.md" in reports else reports[0]))
    if connections:
        parts.append("Automatic connections in analysis\\intel\\: %s. ENTITIES.md lists every person, organization, "
                     "place, document number, structure, station and sheet with its aliases and the files it appears in: "
                     "when the user asks about a structure (MH-3), station (12+50) or sheet (C-104), look it up there "
                     "for the documents that mention it. TIMELINE.md is the automatic timeline, THREADS.md the email "
                     "conversations, VERSIONS.md document versions and what changed, AMOUNTS.md the amounts."
                     % ", ".join(connections))
    return " ".join(parts)


def describe(project):
    d = _ensure_files_dir(project["name"])
    files, _ = list_files(d)
    r = {"project": project["name"], "folders": project["folders"], "notes": _present_notes(project),
         "path": project_file(project["name"]), "files_folder": d, "files": len(files)}
    hint = _analysis_hint(d)
    if hint:
        r["analysis"] = hint
    return r


def resolve(name, active_path):
    """The named project, or the one the open TBC project belongs to."""
    if name:
        project = find_project(name)
        if not project:
            raise KnowledgeError("No project named %r. Use action=link to create it." % name)
        return project
    project = project_for_path(active_path)
    if not project:
        raise KnowledgeError(
            "The open TBC project%s isn't in a known project folder. Ask the user for a project name, then use "
            "action=link (project, optional folder; default: the open project's folder)."
            % (" (%s)" % os.path.basename(active_path) if active_path else ""))
    return project


def list_notes(name, active_path):
    if name:
        return describe(resolve(name, None))
    project = project_for_path(active_path)
    if not project:
        return {"project": None, "open_project": os.path.basename(active_path) if active_path else None,
                "shared_knowledge_dir": shared_root(),
                "known_projects": [{"name": p["name"], "folders": p["folders"], "notes": len(p["notes"])} for p in list_projects()],
                "hint": "No project is linked to this folder yet. If it's one of the known projects (e.g. set up in Civil 3D "
                        "or Project Analyzer), link this folder to it; otherwise ask the user for a project name. Then "
                        "action=link."}
    return describe(project)


def link(name, folder, active_path):
    target = folder or (os.path.dirname(active_path) if active_path and os.path.isabs(active_path) else None)
    if not target:
        raise KnowledgeError("No folder given and the open TBC project's folder isn't known (save the project first).")
    if not slug(name):
        raise KnowledgeError("Give the project a name with letters or digits.")
    check_private_folder(target)
    normalized = normalize_folder(target)
    project = _load_for_write(name)
    created = project is None
    if created:
        project = {"name": one_line(name), "folders": [], "notes": []}
    if any(normalize_folder(f).lower() == normalized.lower() for f in project["folders"]):
        # already linked (by TBC or another tool): nothing to write
        return {"success": True, "action": "unchanged", "project": project["name"], "folders": project["folders"],
                "path": project_file(project["name"]), "files_folder": _ensure_files_dir(project["name"])}
    project["folders"].append(normalized)
    project.setdefault(OWN_FOLDERS, []).append(normalized)
    _save(project)
    return {"success": True, "action": "created" if created else "linked", "project": project["name"],
            "folders": project["folders"], "path": project_file(project["name"]),
            "files_folder": _ensure_files_dir(project["name"])}


def unlink(name, folder):
    if not folder:
        raise KnowledgeError("folder is required")
    project = _load_for_write(name) if slug(name or "") else None
    if not project:
        raise KnowledgeError("No project named %r." % name)
    normalized = normalize_folder(folder).lower()
    if not any(normalize_folder(f).lower() == normalized for f in project["folders"]):
        raise KnowledgeError("%r isn't linked to %r. Linked: %s." % (folder, project["name"], "; ".join(project["folders"]) or "(none)"))
    own = project.get(OWN_FOLDERS) or []
    if not any(normalize_folder(f).lower() == normalized for f in own):
        raise KnowledgeError("%r was linked by another tool (Civil 3D MCP or Project Analyzer), so TBC keeps it: a tool "
                             "unlinks only the folders it linked itself." % folder)
    project["folders"] = [f for f in project["folders"] if normalize_folder(f).lower() != normalized]
    project[OWN_FOLDERS] = [f for f in own if normalize_folder(f).lower() != normalized]
    _save(project)
    return {"success": True, "action": "unlinked", "project": project["name"], "folders": project["folders"]}


def _fresh(project):
    """The job's file as it is on disk right now, for a change (contract rule: re-read before writing)."""
    latest = _load_for_write(project["name"])
    if latest is None:
        raise KnowledgeError("The file for project %r has gone (%s). List the projects again." % (project["name"], project_file(project["name"])))
    return latest


def _clean_note(note):
    text = one_line(note)
    if not text:
        raise KnowledgeError("The note is empty.")
    check_private_text(text)
    return text


def _with_hints(result, text):
    hints = format_hints(text)
    if hints:
        result["format_hints"] = ("Saved. Next time use the suite's reference formats so Project Analyzer connects the "
                                  "note to the same items in documents: %s (%s)." % ("; ".join(hints), REFERENCE_FORMATS))
    return result


def add_note(note, name, active_path):
    text = _clean_note(note)
    project = _fresh(resolve(name, active_path))  # merge into what's on disk now
    duplicate = next((n for n in project["notes"] if isinstance(n, dict) and n.get("note", "").lower() == text.lower()), None)
    if duplicate:
        return {"success": True, "action": "unchanged", "project": project["name"], "note": dict(duplicate, by=origin(duplicate))}
    numbers = [int(re.sub(r"\D", "", str(n.get("id", ""))) or 0) for n in project["notes"] if isinstance(n, dict)]
    entry = {"id": "note-%d" % (max(numbers + [0]) + 1), "note": text, "added": _now(), "source": SOURCE}
    project["notes"].append(entry)
    _save(project)
    return _with_hints({"success": True, "action": "added", "project": project["name"], "note": entry,
                        "path": project_file(project["name"])}, text)


def _own_note(project, note_id):
    entry = next((n for n in project["notes"] if isinstance(n, dict) and n.get("id") == note_id), None)
    if not entry:
        raise KnowledgeError("No note %r in project %r." % (note_id, project["name"]))
    if origin(entry) != SOURCE:
        raise KnowledgeError("%s was written by %s, which owns it. Don't rewrite or remove another tool's notes: add a new "
                             "note that corrects it (action=add)." % (note_id, TOOL_LABELS.get(origin(entry), origin(entry))))
    return entry


def update_note(note_id, note, name, active_path):
    text = _clean_note(note)
    project = _fresh(resolve(name, active_path))
    entry = _own_note(project, note_id)
    entry["note"] = text
    entry["updated"] = _now()
    _save(project)
    return _with_hints({"success": True, "action": "updated", "project": project["name"], "note": entry}, text)


def remove_note(note_id, name, active_path):
    project = _fresh(resolve(name, active_path))
    entry = _own_note(project, note_id)
    project["notes"] = [n for n in project["notes"] if n is not entry]
    _save(project)
    return {"success": True, "action": "removed", "project": project["name"], "note": entry}


def project_files(name, active_path):
    project = resolve(name, active_path)
    d = _ensure_files_dir(project["name"])
    files, truncated = list_files(d)
    r = {"project": project["name"], "files_folder": d, "files": files, "truncated": truncated,
         "hint": "Empty. The user can drop PDFs, Word/Excel files, images or anything else here (subfolders are fine)."
         if not files else "Read text files with action=read (file=<path as listed>). Project-specific: keep findings in "
                           "project notes, not in general lessons or skills."}
    hint = _analysis_hint(d)
    if hint:
        r["analysis"] = hint
    return r


def read_file(rel, name, active_path, max_chars=MAX_READ_CHARS):
    """Text of one file in the project's files folder (paths outside it are refused)."""
    if not rel:
        raise KnowledgeError("file is required (a path as listed by action=files, e.g. analysis\\OVERVIEW.md)")
    project = resolve(name, active_path)
    d = os.path.realpath(_ensure_files_dir(project["name"]))
    full = os.path.realpath(os.path.join(d, rel))
    try:
        inside = os.path.commonpath([d, full]).lower() == d.lower()
    except ValueError:  # another drive
        inside = False
    if not inside:
        raise KnowledgeError("Only files inside the project's files folder can be read.")
    if not os.path.isfile(full):
        raise KnowledgeError("No file %r in %s. Use action=files to list them." % (rel, d))
    with open(full, "rb") as f:
        raw = f.read(max_chars * 4 + 1)
    ext = os.path.splitext(full)[1].lower()
    if ext not in TEXT_EXTENSIONS and b"\0" in raw[:4096]:
        raise KnowledgeError("%s isn't a text file. Ask the user what's in it, or open it with a tool that reads that type." % rel)
    text = raw.decode("utf-8-sig", errors="replace")
    max_chars = int(max_chars)
    r = {"project": project["name"], "file": os.path.relpath(full, d), "size": os.path.getsize(full),
         "text": text[:max_chars]}
    if len(text) > max_chars or os.path.getsize(full) > len(raw):
        r["truncated"] = True
    return r


# Notes are attached to results once per project per server run, so they reach the AI without repeating.
_announced = set()


def notes_once(active_path):
    try:
        project = project_for_path(active_path)
        if not project or project["name"] in _announced:
            return None
        d = files_dir(project["name"])
        files = [f["path"] for f in list_files(d, 50)[0]]
        if not project["notes"] and not files:
            return None
        _announced.add(project["name"])
        r = {"project": project["name"], "notes": _present_notes(project), "files_folder": d, "files": files,
             "hint": "Shared project knowledge (also used by Civil 3D MCP and Project Analyzer). Follow these facts; "
                     "add what you learn about this job with tbc_project_notes action=add (ask the user first), "
                     "in the suite's reference formats: %s." % REFERENCE_FORMATS}
        hint = _analysis_hint(d)
        if hint:
            r["analysis"] = hint
        return r
    except (OSError, ValueError, KnowledgeError):
        return None


def reset_announcements():
    """For tests."""
    _announced.clear()
