# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Project knowledge shared with civil3d-mcp-unified and project-analyzer: one knowledge base per job for the whole suite.

The contract all three follow is project-analyzer's docs/shared-project-knowledge.md. In short, the three tools keep
what they learn about ONE job in the same plain files, so facts the Civil 3D assistant or Project Analyzer recorded
come back in TBC, and the other way round:

    <shared dir>\\projects\\<slug>.json   {name, folders, notes: [{id: note-N, note, added, updated?, source?}], ...}
    <shared dir>\\projects\\<slug>\\      the job's files folder: reference files the user drops in, and Project
                                         Analyzer's reports: analysis\\ (OVERVIEW.md, TIMELINE.md, PEOPLE.md,
                                         ISSUES.md, INDEX.md) and analysis\\intel\\ (CHECKS.md, STORIES.md,
                                         ENTITIES.md, TIMELINE.md, THREADS.md, VERSIONS.md, AMOUNTS.md, plus the
                                         graph.html / timeline.html pages for people to open in a browser)

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
  - copied folders: a job folder is usually a COPY of a project from elsewhere, so paths written in its files (a TBC
    project's imported files and linked data) point at the original location. locate() translates them to the copy
    with Project Analyzer's relink_map.csv and project-analyzer_original_locations, and never guesses
"""
import csv
import datetime
import json
import ntpath
import os
import re
import urllib.parse

from knowledge import KnowledgeError

FOLDER_NAME = "Civil3DMcp-KnowledgeBase"
LEGACY_FOLDER_NAME = "Civil3DMcp"      # Civil 3D MCP's default before 2.2.0
SOURCE = "tbc"                         # marks the notes TBC wrote (the other tools keep unknown fields)
OWN_FOLDERS = "tbc_linked_folders"     # TBC's own top-level field: the folders it linked (only those can be unlinked)
MAX_READ_CHARS = 20000
ANALYSIS_REPORTS = ("OVERVIEW.md", "TIMELINE.md", "PEOPLE.md", "ISSUES.md", "INDEX.md")
INTEL_REPORTS = ("CHECKS.md", "STORIES.md", "ENTITIES.md", "TIMELINE.md", "THREADS.md", "VERSIONS.md", "AMOUNTS.md",
                 "REFERENCES.md", "relink_map.csv")
# Project Analyzer's fields in <slug>.json about the copy (contract: Copied project folders); read, never written
ANALYZER_ROOT = "project-analyzer_root"
ANALYZER_COPY = "project-analyzer_copy"
ANALYZER_ORIGINALS = "project-analyzer_original_locations"
RELINK_COLUMNS = ("path as written in the files", "relative path in this folder", "status", "expected at", "times referenced")
# Interactive pages for people: their data is one big embedded JSON block, useless to the AI as text
INTEL_PAGES = ("graph.html", "timeline.html")

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

# Project Analyzer's notes end "[source: <file>; fact-N]"; its first note points to the reports (analyzer/shared.py)
_ANALYZER_NOTE = re.compile(r"; fact-\d+\]$")
_ANALYZER_POINTER = "Full analysis of this project (overview, timeline, people, issues, index) is in this project's files"

_migration_checked = [False]


def _documents():
    """The user's Documents folder the way Civil 3D MCP finds it (<home>\\Documents, not a redirected shell folder),
    so every tool agrees on the default shared folder."""
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
    """The shared knowledge folder: CIVIL3D_KNOWLEDGE_DIR when set, else Documents\\Civil3DMcp-KnowledgeBase (first
    moving the pre-2.2.0 folder there, once per run, as Civil 3D MCP does)."""
    configured = os.environ.get("CIVIL3D_KNOWLEDGE_DIR", "").strip()
    if configured:
        return configured
    documents = _documents()
    if not _migration_checked[0]:
        _migration_checked[0] = True
        migrate_legacy_folder(documents)
    return os.path.join(documents, FOLDER_NAME)


def projects_dir():
    """<shared dir>\\projects, where each job's <slug>.json and its files folder live."""
    return os.path.join(shared_root(), "projects")


def slug(name):
    """Same as projectNotes.ts: lowercase, non-alphanumerics to '-', trimmed, at most 64 characters."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")[:64]


def one_line(value):
    """Collapse line breaks into spaces and trim: every note is one line."""
    return re.sub(r"[\r\n]+", " ", value or "").strip()


def normalize_folder(folder):
    """Absolute folder path without a trailing slash, for comparing linked folders."""
    return os.path.abspath(folder).rstrip("\\/")


def _now():
    # Same form as JavaScript's toISOString(), which the other tools write
    """UTC time in JavaScript's toISOString() form (2026-10-25T21:42:47.123Z), the timestamp format of the shared
    files."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _write_atomically(path, text):
    """Write text to a temp file in the same folder, then rename it over the target (contract rule 3): UTF-8 without
    BOM, LF line endings."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = os.path.join(os.path.dirname(path), ".%s.%d.%d.tmp" % (os.path.basename(path), os.getpid(),
                                                                  int(datetime.datetime.now().timestamp() * 1000)))
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def project_file(name):
    """<shared dir>\\projects\\<slug>.json for a job name; KnowledgeError when the name has no letters or digits."""
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
    """Write a job file back atomically, with every field kept as loaded."""
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
    """The user's profile folder, normalized and lowercased, for the privacy checks."""
    return normalize_folder(os.path.expanduser("~")).lower()


def check_private_text(text):
    """Raise KnowledgeError when text holds a registered private value (bridge session token, license fingerprint)
    or a path inside the user's profile. Used for shared notes, and by knowledge.check_general for general
    knowledge."""
    low = (text or "").lower().replace("/", "\\")
    found = sorted({what for value, what in _private.items() if value in low})
    if _profile() and _profile() + "\\" in low:
        found.append("a path inside your user profile (write the file name, or the path inside the job folder)")
    if found:
        raise KnowledgeError("Shared project notes must not contain %s. Notes are shared with other tools and people; "
                             "rewrite the note without it." % " or ".join(found))


def check_private_folder(folder):
    """Raise KnowledgeError when a folder is the profile root, or inside AppData, temp or TBC MCP's private folder:
    those can never be linked to a shared job."""
    f = normalize_folder(folder).lower()
    if f == _profile() or any(f == r or f.startswith(r + "\\") for r in _private_folders()):
        raise KnowledgeError("%s is a private per-user folder (user profile, AppData or temp), so it can't be linked to "
                             "a shared job. Link the job's own folder (drawings, TBC projects, documents)." % folder)


def format_hints(text):
    """Reference-format reminders for a note (it is still saved: they're advice, not rules)."""
    return sorted({hint for rx, hint in _FORMAT_CHECKS if rx.search(text)})


def list_projects():
    """Every job in the shared projects folder, as dicts. Files that don't parse are skipped, never rewritten."""
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
    """The job with this name, read fresh from disk, or None when there is no such file."""
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
    """A job's notes as returned to the AI: each gets 'by' (the tool that wrote it); entries that aren't objects are
    left out."""
    return [dict(n, by=origin(n)) for n in project["notes"] if isinstance(n, dict)]


def list_files(directory, limit=500):
    """Files under a job's files folder: relative path, size and UTC modified time, sorted, at most `limit`. Returns
    (files, truncated)."""
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
    """The job's files folder, created when missing (Civil 3D MCP does the same when a project is listed)."""
    d = files_dir(name)
    os.makedirs(d, exist_ok=True)
    return d


def _analysis_hint(directory, project=None):
    """What Project Analyzer has written for this job, and how to use it, or None."""
    analysis, intel = os.path.join(directory, "analysis"), os.path.join(directory, "analysis", "intel")
    reports = [r for r in ANALYSIS_REPORTS if os.path.isfile(os.path.join(analysis, r))]
    findings = [r for r in INTEL_REPORTS if os.path.isfile(os.path.join(intel, r))]
    pages = intel_pages(directory)
    copied = project is not None and any(_copy_info(project)[:2])
    if not reports and not findings and not pages and not copied:
        return None
    parts = ["Project Analyzer has analysed this job's documents (read them with tbc_project_notes action=read file=...)."]
    if reports:
        parts.append("Reports in analysis\\: %s - start with %s. Their facts cite the source files."
                     % (", ".join(reports), "OVERVIEW.md" if "OVERVIEW.md" in reports else reports[0]))
    if findings:
        parts.append("Automatic findings in analysis\\intel\\: %s." % ", ".join(findings))
        uses = {
            "CHECKS.md": "CHECKS.md lists problems to follow up (Needs attention / Worth checking / For information: "
                         "conflicting amounts, RFIs with no reply, missing documents, date conflicts, versions dated "
                         "after the FINAL one, quiet periods) - before relying on a document or number that might be "
                         "in dispute (an amount, a revision, a sheet), check it there.",
            "STORIES.md": "STORIES.md follows each RFI, change order, submittal and other reference from first mention "
                          "to last, with the people and amounts (references that travel together are one story, e.g. "
                          "'CO 4 -> RFI 12') - when the user asks about an RFI, change order or submittal, read its story.",
            "ENTITIES.md": "ENTITIES.md lists every person, organization, place, document number, structure, station and "
                           "sheet with its aliases and the files it appears in - when the user asks about a structure "
                           "(MH-3), station (12+50) or sheet (C-104), look it up there for the documents that mention it.",
            "TIMELINE.md": "TIMELINE.md is the automatic timeline.",
            "THREADS.md": "THREADS.md the email conversations.",
            "VERSIONS.md": "VERSIONS.md document versions and what changed.",
            "AMOUNTS.md": "AMOUNTS.md the amounts.",
            "REFERENCES.md": "REFERENCES.md lists the files the job's files point at that are missing from the copy, "
                             "where each belongs and which files need it.",
            "relink_map.csv": "relink_map.csv maps every path written in the files to its place in the copy - use "
                              "tbc_project_notes action=locate (path) rather than reading it.",
        }
        parts.extend(uses[r] for r in findings)
    if pages:
        parts.append("Interactive pages for the user to open in a browser (not readable as text): %s."
                     % "; ".join(pages))
    if project is not None:
        root, originals, copy = _copy_info(project)
        if root or originals or "relink_map.csv" in findings:
            parts.append("COPIED FOLDER: this job's folder is a copy%s%s, so paths written in its files - a TBC "
                         "project's imported files, linked images and data sources - still point at the original "
                         "location. When TBC reports a missing or unresolved file, or a path the user mentions doesn't "
                         "exist, use tbc_project_notes action=locate (path) before telling the user it's missing; an "
                         "existing path isn't necessarily the right file either."
                         % (" (top folder %s)" % root if root else "",
                            "; originally %s" % ", ".join(o for o, _ in originals) if originals else ""))
    return " ".join(parts)


def intel_pages(directory):
    """Full paths of Project Analyzer's interactive pages (graph.html, timeline.html) that exist for this job."""
    intel = os.path.join(directory, "analysis", "intel")
    return [os.path.join(intel, p) for p in INTEL_PAGES if os.path.isfile(os.path.join(intel, p))]


_SECTION = re.compile(r"^##\s+(Needs attention|Worth checking|For information)\b[^\n(]*(?:\((\d+)\))?", re.I)
_ITEM = re.compile(r"^###\s+(.+?)\s*$")


def read_checks(directory, limit=5):
    """The open problems in analysis\\intel\\CHECKS.md: titles of the 'Needs attention' items (at most `limit`) and
    the counts per section, from the '## <section> (N)' headings (or the '### ' items when a heading has no count).
    None when the file is missing, unreadable or has none of the sections; never raises."""
    path = os.path.join(directory, "analysis", "intel", "CHECKS.md")
    try:
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            lines = f.read(2000000).splitlines()
        sections, current = {}, None
        for line in lines:
            m = _SECTION.match(line)
            if m:
                current = m.group(1).lower()
                sections[current] = {"count": int(m.group(2)) if m.group(2) else None, "titles": []}
            elif line.startswith("## "):
                current = None
            elif current:
                item = _ITEM.match(line)
                if item:
                    sections[current]["titles"].append(item.group(1))
        if not sections:
            return None
        count = lambda s: (sections[s]["count"] if sections[s]["count"] is not None else len(sections[s]["titles"])) if s in sections else 0
        attention = sections.get("needs attention", {"titles": []})["titles"]
        return {"file": path, "needs_attention": count("needs attention"), "needs_attention_titles": attention[:limit],
                "worth_checking": count("worth checking"), "for_information": count("for information"),
                "hint": "Open problems Project Analyzer found in this job's documents. Mention the ones that bear on "
                        "the user's task; read analysis\\intel\\CHECKS.md (tbc_project_notes action=read) for details."}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# copied project folders: where a path written in the job's files is in the copy (contract: Copied project folders)
# ---------------------------------------------------------------------------
def to_windows(raw):
    """Normalizes a path the way Project Analyzer writes column 1 of relink_map.csv (its references.to_windows):
    'file:///P:/Jobs/1234%20Elm/x.pdf' -> 'P:\\Jobs\\1234 Elm\\x.pdf'; forward slashes -> backslashes."""
    s = (raw or "").strip().strip("\"'")
    m = re.match(r"(?i)^file:(/*)(.*)$", s)
    if m:
        slashes, rest = m.group(1), urllib.parse.unquote(m.group(2))
        s = rest if re.match(r"^[A-Za-z]:", rest) else ("\\\\" + rest if len(slashes) == 2 else rest)
    elif "%20" in s:
        s = urllib.parse.unquote(s)
    s = s.replace("/", "\\")
    if s.startswith("\\\\"):
        return "\\\\" + ntpath.normpath(s[2:])
    return ntpath.normpath(s) if s else s


_relink_cache = {}  # csv path -> (mtime, size, rows by lowercased path)


def read_relink_map(directory):
    """analysis\\intel\\relink_map.csv as {lowercased normalized path: row}, or None when it is missing or malformed.
    Read only (utf-8-sig); never raises."""
    path = os.path.join(directory, "analysis", "intel", "relink_map.csv")
    try:
        st = os.stat(path)
    except OSError:
        return None
    cached = _relink_cache.get(path)
    if cached and cached[:2] == (st.st_mtime, st.st_size):
        return cached[2]
    rows = None
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = [h.strip().lower() for h in next(reader, [])]
            if all(c in header for c in RELINK_COLUMNS[:3]):
                col = {c: header.index(c) for c in RELINK_COLUMNS if c in header}
                rows = {}
                for rec in reader:
                    if len(rec) < 3:
                        continue  # blank or broken line
                    get = lambda c: rec[col[c]].strip() if c in col and col[c] < len(rec) else ""
                    written = to_windows(get("path as written in the files"))
                    if not written:
                        continue
                    try:
                        times = int(get("times referenced") or 0)
                    except ValueError:
                        times = 0
                    rows[written.lower()] = {"written": written, "relative": get("relative path in this folder"),
                                             "status": get("status").lower(), "expected": get("expected at"), "times": times}
    except (OSError, UnicodeDecodeError, csv.Error):
        rows = None
    _relink_cache[path] = (st.st_mtime, st.st_size, rows)
    return rows


def _copy_info(project):
    """Project Analyzer's description of the copy: (root or None, [(original, in_copy)], copy note or None)."""
    root = project.get(ANALYZER_ROOT)
    root = root if isinstance(root, str) and root.strip() else None
    originals = []
    for o in project.get(ANALYZER_ORIGINALS) or []:
        if isinstance(o, dict) and isinstance(o.get("original"), str) and o["original"].strip():
            originals.append((to_windows(o["original"]), to_windows(str(o.get("in_copy") or ""))))
    originals.sort(key=lambda o: -len(o[0]))  # the most specific original folder wins
    copy = project.get(ANALYZER_COPY)
    return root, originals, (copy if copy not in (None, "", {}, []) else None)


def _in_copy(root, relative):
    """(absolute path, exists) for a path relative to the copy's root; (None, False) without a root."""
    if not root or not relative:
        return None, False
    full = os.path.normpath(os.path.join(root, to_windows(relative)))
    return full, os.path.exists(full)


def references_summary(directory):
    """How many referenced files are missing from the copy (one per distinct path), for the start of a session."""
    rows = read_relink_map(directory)
    if not rows:
        return None
    counts = {}
    for r in rows.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    out = {"missing": counts.get("missing", 0), "ambiguous": counts.get("ambiguous", 0),
           "found": counts.get("found", 0) + counts.get("found by name", 0),
           "file": os.path.join(directory, "analysis", "intel", "REFERENCES.md")}
    out["hint"] = ("This job's folder is a copy: paths written in its files (TBC imported files, linked images and data) "
                   "point at the original location. %d referenced file(s) are missing from the copy - REFERENCES.md "
                   "says what, where each belongs and which files need it. Before telling the user a file is "
                   "missing, translate its path with tbc_project_notes action=locate." % out["missing"])
    return out


def locate(path, name, active_path):
    """Where a path as TBC or a file shows it is in the job's copy: relink_map.csv first, then
    project-analyzer_original_locations, then a check on disk. Never guesses."""
    if not path or not str(path).strip():
        raise KnowledgeError("path is required: the file path as TBC or a file shows it")
    project = resolve(name, active_path)
    d = files_dir(project["name"])
    root, originals, copy = _copy_info(project)
    written = to_windows(str(path))
    r = {"project": project["name"], "path": str(path), "normalized": written, "copy_root": root}
    if copy is not None:
        r["copy"] = copy
    record = ("If the user confirms this (or relinks the file in TBC), offer to record it as a project note, asking "
              "first, e.g. 'Imported file <path as written> is <path in the copy, relative to its top folder> in the "
              "copy [source: TBC project <name>.vce]'.")

    rows = read_relink_map(d)
    row = rows.get(written.lower()) if rows else None
    if row:
        r["source"] = "relink_map.csv"
        r["status"] = row["status"] or "unknown"
        r["times_referenced"] = row["times"]
        full, exists = _in_copy(root, row["relative"])
        if row["relative"]:
            r["relative"] = row["relative"]
            r["absolute"] = full
            r["exists"] = exists
        if r["status"] == "missing" or not row["relative"]:
            if row["expected"]:
                where, _ = _in_copy(root, row["expected"])
                r["expected_at"] = {"relative": row["expected"], "absolute": where}
        if r["status"] == "missing":
            r["hint"] = ("Not in the copy. It belongs at %s (see analysis\\intel\\REFERENCES.md). Ask the user for the "
                         "file; don't point TBC at another file." % (row["expected"] or "a place Project Analyzer could not tell"))
        elif r["status"] == "ambiguous":
            r["hint"] = ("More than one file in the copy could be this one; analysis\\intel\\REFERENCES.md lists the "
                         "candidates. Ask the user which is right - don't pick one.")
        elif r["status"] == "found by name":
            r["hint"] = "Matched by file name only, elsewhere in the copy: check with the user that it's the right file. " + record
        else:
            r["hint"] = record
        if row["relative"] and not root:
            r["note"] = "Project Analyzer didn't record the copy's top folder, so only the relative path is known."
        elif row["relative"] and not exists:
            r["note"] = ("The copy's top folder (%s) isn't reachable from this computer, or the file was moved since "
                         "the analysis." % root)
        return r

    low = written.lower()
    for original, in_copy in originals:
        o = original.lower().rstrip("\\")
        if low == o or low.startswith(o + "\\"):
            rest = written[len(o):].lstrip("\\")
            relative = ntpath.join(in_copy, rest) if in_copy and in_copy != "." else rest
            full, exists = _in_copy(root, relative)
            r.update({"source": ANALYZER_ORIGINALS, "original_folder": original, "relative": relative,
                      "absolute": full, "exists": exists,
                      "status": "translated" if exists else "translated, not found"})
            if not root:
                r["note"] = "Project Analyzer didn't record the copy's top folder, so only the relative path is known."
            r["hint"] = (record if exists else
                         "Under the original folder %s, so in the copy it would be %s - but no file is there. It may "
                         "not have been copied: ask the user for it." % (original, full or relative))
            return r

    r.update({"status": "not known", "source": None,
              "hint": "Neither Project Analyzer's relink map nor its list of original locations covers this path, so "
                      "where it is in the copy isn't known. Don't guess: ask the user where the original project folder "
                      "was (or where this file is now)."})
    if not rows and not originals:
        r["note"] = ("Project Analyzer hasn't mapped this job's copy yet (no relink_map.csv or original locations): "
                     "the user can run its analysis, or tell you where the original folder was.")
    try:
        if os.path.isabs(written) and os.path.exists(written):
            r["exists_as_written"] = True
            r["note"] = ((r.get("note", "") + " ").lstrip() + "A file does exist at that path, but it isn't known to "
                         "be this job's copy of it: check with the user before using it.")
    except (OSError, ValueError):
        pass
    return r


def describe(project):
    """Everything tbc_project_notes action=list returns for one job: folders, notes with their authors, the job
    file's path, the files folder with its file count, and Project Analyzer's hint."""
    d = _ensure_files_dir(project["name"])
    files, _ = list_files(d)
    r = {"project": project["name"], "folders": project["folders"], "notes": _present_notes(project),
         "path": project_file(project["name"]), "files_folder": d, "files": len(files)}
    hint = _analysis_hint(d, project)
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
    """action=list: the named job, or the job the open .vce belongs to. When no job matches, the known jobs and a
    hint to link one."""
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
    """action=link: create a job, or add a folder to one (default: the open .vce's folder). The folder is also
    recorded in TBC's own tbc_linked_folders field; a folder already linked by any tool changes nothing; private
    per-user folders are refused."""
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
    """action=unlink: drop a folder TBC linked itself (contract rule 2: never another tool's). The job and its notes
    stay."""
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
    """A note's text made one line and checked for private data; KnowledgeError when it is empty or private."""
    text = one_line(note)
    if not text:
        raise KnowledgeError("The note is empty.")
    check_private_text(text)
    return text


def _with_hints(result, text):
    """Add reference-format reminders to a write result when the note wasn't written in the suite's formats."""
    hints = format_hints(text)
    if hints:
        result["format_hints"] = ("Saved. Next time use the suite's reference formats so Project Analyzer connects the "
                                  "note to the same items in documents: %s (%s)." % ("; ".join(hints), REFERENCE_FORMATS))
    return result


def add_note(note, name, active_path):
    """action=add: append {id: note-N, note, added, source: 'tbc'} to the job, merged into the file as it is on disk
    now. The same text, in any case, returns the existing note (action='unchanged')."""
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
    """The note with this id when TBC wrote it; KnowledgeError for an unknown id or another tool's note."""
    entry = next((n for n in project["notes"] if isinstance(n, dict) and n.get("id") == note_id), None)
    if not entry:
        raise KnowledgeError("No note %r in project %r." % (note_id, project["name"]))
    if origin(entry) != SOURCE:
        raise KnowledgeError("%s was written by %s, which owns it. Don't rewrite or remove another tool's notes: add a new "
                             "note that corrects it (action=add)." % (note_id, TOOL_LABELS.get(origin(entry), origin(entry))))
    return entry


def update_note(note_id, note, name, active_path):
    """action=update: replace the text of one of TBC's own notes and stamp 'updated' (unknown fields on the note are
    kept)."""
    text = _clean_note(note)
    project = _fresh(resolve(name, active_path))
    entry = _own_note(project, note_id)
    entry["note"] = text
    entry["updated"] = _now()
    _save(project)
    return _with_hints({"success": True, "action": "updated", "project": project["name"], "note": entry}, text)


def remove_note(note_id, name, active_path):
    """action=remove: delete one of TBC's own notes. Another tool's note is refused; it is corrected by adding a
    note instead."""
    project = _fresh(resolve(name, active_path))
    entry = _own_note(project, note_id)
    project["notes"] = [n for n in project["notes"] if n is not entry]
    _save(project)
    return {"success": True, "action": "removed", "project": project["name"], "note": entry}


def project_files(name, active_path):
    """action=files: the job's files folder listing, Project Analyzer's hint, and its interactive pages for the user
    to open."""
    project = resolve(name, active_path)
    d = _ensure_files_dir(project["name"])
    files, truncated = list_files(d)
    r = {"project": project["name"], "files_folder": d, "files": files, "truncated": truncated,
         "hint": "Empty. The user can drop PDFs, Word/Excel files, images or anything else here (subfolders are fine)."
         if not files else "Read text files with action=read (file=<path as listed>). Project-specific: keep findings in "
                           "project notes, not in general lessons or skills."}
    hint = _analysis_hint(d, project)
    if hint:
        r["analysis"] = hint
    pages = intel_pages(d)
    if pages:
        r["pages_to_open"] = [{"page": os.path.basename(p), "path": p, "open": "in a browser (for the user, not as text)"}
                              for p in pages]
    return r


def _is_intel_page(full, d):
    """True for this job's analysis\\intel\\graph.html or timeline.html, which action=read answers with 'open it in
    a browser' instead of the HTML."""
    return (os.path.basename(full).lower() in INTEL_PAGES
            and os.path.normcase(os.path.dirname(full)) == os.path.normcase(os.path.join(d, "analysis", "intel")))


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
    if _is_intel_page(full, d):
        return {"project": project["name"], "file": os.path.relpath(full, d), "page": full,
                "message": "%s is an interactive page for people: its data is one large embedded JSON block, not useful "
                           "as text. Tell the user to open it in a browser: %s. For the same information as text, read "
                           "the .md reports in analysis\\intel\\ (STORIES.md, ENTITIES.md, TIMELINE.md)."
                           % (os.path.basename(full), full)}
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
    """What the first result of a session carries for the open job: its notes and files, Project Analyzer's hint,
    the open problems from CHECKS.md and the count of missing referenced files. None when there's nothing to
    show, when this job was already announced in this server run, or on any error (project notes are advice and
    never break a call)."""
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
        hint = _analysis_hint(d, project)
        if hint:
            r["analysis"] = hint
        checks = read_checks(d)  # never raises: a missing or odd CHECKS.md just leaves this out
        if checks:
            r["checks"] = checks
        try:
            refs = references_summary(d)  # likewise for relink_map.csv
        except Exception:
            refs = None
        if refs:
            r["references"] = refs
        return r
    except (OSError, ValueError, KnowledgeError):
        return None


def reset_announcements():
    """For tests."""
    _announced.clear()
