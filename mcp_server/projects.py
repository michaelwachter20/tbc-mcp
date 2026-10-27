# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Project knowledge shared with civil3d-mcp-unified and project-analyzer: one SQLite database per job for the suite.

The contract all three follow is project-analyzer's docs/suite-knowledge.md; the exact table layout is its
schema/project-db.sql, shipped here as mcp_server/project-db.sql (a byte-for-byte copy: tests/test_project_db.py
fails when it differs from the analyzer's, when that repository is next to this one). In short:

    <shared>\\projects\\<slug>.db      everything about one job: the analyzer's files, text (zstd-compressed),
                                       references, automatic findings (intel_*), and the facts every tool learned
    <shared>\\projects\\<slug>\\User Knowledge\\   the user's own documents for the job (guidelines, requirements,
                                       standards); only read (Project Analyzer reads them into the database too)
    <shared>\\practices.json           good practices of the whole suite (practices.py)

<shared> is the suite's folder, found the same way by all three tools (knowledge.shared_dir): PROJECT_KNOWLEDGE_DIR,
else Documents\\Project Knowledge, or an earlier folder (Documents\\Civil3DMcp-KnowledgeBase) used as it is.

What TBC does with it:
  - finds the job of the open .vce: meta.source_root and every `folders` row, across all <shared>\\projects\\*.db,
    case-insensitive on normalized absolute paths, the deepest folder wins (job_index, cached by file stamps)
  - reads: overview, search (full-text index + facts), file, entity, timeline, locate (copied job folders), list,
    and the job's user knowledge (files, read; also in overview and search): the analyzer's stored text when it read
    that version of a document, else the file itself (text, .docx, .xlsx, .pptx via office_text.py)
  - works with no other suite tool installed: creates the database and the User Knowledge folder when needed
  - writes only its own rows: facts with tool='tbc' (add with a duplicate check and fact-N taken inside a
    BEGIN IMMEDIATE transaction; update; remove = set `retired`, nothing is deleted) and folders with tool='tbc'
    (link / unlink). Another tool's fact is corrected by adding one with `supersedes` set to it.
  - creates the database when the user links a new job (runs project-db.sql, sets schema_version, project_id,
    created, project_name), and imports an old <slug>.json notes file once (import_json_notes, as the contract says)
  - never writes to a database whose meta.schema_version is newer than it knows (reads it as far as it can)
  - privacy: no license details, session tokens or user-profile paths in facts or folders
  - never keeps a copy of a job's files; text is read from the database, decompressed in memory

Connections use autocommit (isolation_level=None) and explicit BEGIN IMMEDIATE ... COMMIT for writes, so two tools
(an 8-hour analyzer run and this server adding a fact) share the file: WAL journal, 30 s busy timeout.
"""
import contextlib
import datetime
import json
import ntpath
import os
import re
import secrets
import sqlite3
import urllib.parse

import office_text
from knowledge import KnowledgeError, shared_root  # noqa: F401 (re-exported for callers)

TOOL = "tbc"                          # the `tool` value of every row TBC writes
SCHEMA_VERSION = 1
# A copy of project-analyzer's schema/project-db.sql (see the module docstring); run when TBC creates a database
SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "project-db.sql")
MAX_READ_CHARS = 20000                # action=read (a document in the job's User Knowledge folder)
USER_KNOWLEDGE_FOLDER = "User Knowledge"
USER_PREFIX = "<user knowledge>\\"   # files.path of a user-knowledge document read by Project Analyzer
MAX_SCAN_FILES, MAX_SCAN_BYTES = 200, 20 * 1024 * 1024   # search: documents not in the database, read directly
FILE_TEXT_CHARS = 4000                # action=file: the first part of a file's text
TOOL_LABELS = {"civil3d": "Civil 3D MCP", "project-analyzer": "Project Analyzer", TOOL: "TBC MCP"}

# How every tool in the suite writes references, so Project Analyzer's automatic connections tie a fact to the same
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
BINARY_EXTENSIONS = {".pdf", ".doc", ".xls", ".ppt", ".rtf", ".odt", ".dwg", ".dgn", ".jpg", ".jpeg", ".png", ".tif",
                     ".tiff", ".bmp", ".gif", ".zip", ".7z", ".msg", ".eml", ".pst", ".vce", ".exe", ".dll"}
_DATE = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")


def projects_dir():
    """<shared>\\projects, where each job's <slug>.db and its folder (with User Knowledge) live."""
    return os.path.join(shared_root(), "projects")


def slug(name):
    """Same as the contract and projectNotes.ts: lowercase, non-alphanumerics to '-', trimmed, at most 64 chars."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")[:64]


def one_line(value):
    """Collapse line breaks and runs of spaces: every fact is one line."""
    return " ".join((value or "").split())


def normalize_folder(folder):
    """Absolute folder path without a trailing slash, for comparing linked folders."""
    return os.path.abspath(folder).rstrip("\\/")


def _key(folder):
    """A folder as compared for matching: normalized, backslashes, lower case."""
    return normalize_folder(folder).replace("/", "\\").lower()


def _now():
    """UTC time in JavaScript's toISOString() form (2026-10-25T21:42:47.123Z), every time stored in the database."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def db_path(name):
    """<shared>\\projects\\<slug>.db for a job name; KnowledgeError when the name has no letters or digits."""
    key = slug(name)
    if not key:
        raise KnowledgeError("Give the project a name with letters or digits.")
    return os.path.join(projects_dir(), key + ".db")


def files_dir(name):
    """The job's User Knowledge folder, <shared>\\projects\\<slug>\\User Knowledge (next to <slug>.db)."""
    return os.path.join(db_path(name)[:-len(".db")], USER_KNOWLEDGE_FOLDER)


def _loads(text, default):
    """A JSON column's value, or `default` when it is empty or not JSON."""
    try:
        value = json.loads(text) if text else default
    except (TypeError, ValueError):
        return default
    return value if value is not None else default


# ---------------------------------------------------------------------------
# text: zstd blocks (contract: Reading text)
# ---------------------------------------------------------------------------
_zstd = [None]  # the decompress function once looked up; False when no zstd library is installed


def _zstd_decompress(data):
    """Decompress one zstd frame with the `zstandard` package (or Python 3.14's compression.zstd)."""
    if _zstd[0] is None:
        try:
            import zstandard
            _zstd[0] = zstandard.ZstdDecompressor().decompress
        except ImportError:
            try:
                from compression import zstd  # Python 3.14+
                _zstd[0] = zstd.decompress
            except ImportError:
                _zstd[0] = False
    if not _zstd[0]:
        raise KnowledgeError("The job's text is stored zstd-compressed and the zstandard package isn't installed. Ask "
                             "the user to run: py -3.12 -m pip install zstandard (then restart the AI app).")
    return _zstd[0](data)


def decompress(codec, data):
    """A text block's bytes by its codec: 'zstd', 'zlib' or 'none'."""
    if codec == "zstd":
        return _zstd_decompress(bytes(data))
    if codec == "zlib":
        import zlib
        return zlib.decompress(data)
    if codec == "none":
        return bytes(data)
    raise KnowledgeError("Unknown text codec %r in the project database (update TBC MCP)." % codec)


class _Blocks(object):
    """Decompressed text blocks of one request, each decompressed once."""

    def __init__(self, db):
        self.db, self.cache = db, {}

    def part(self, part_id):
        """(file id, label, text) of one text part."""
        p = self.db.execute("SELECT file_id, label, block_id, offset, length FROM text_parts WHERE id = ?",
                            (part_id,)).fetchone()
        if not p:
            return None, None, ""
        return p["file_id"], p["label"], self._slice(p)

    def _slice(self, p):
        if p["block_id"] not in self.cache:
            b = self.db.execute("SELECT codec, data FROM text_blocks WHERE id = ?", (p["block_id"],)).fetchone()
            self.cache[p["block_id"]] = decompress(b["codec"], b["data"]) if b else b""
        return self.cache[p["block_id"]][p["offset"]:p["offset"] + p["length"]].decode("utf-8", errors="replace")

    def file_text(self, file_id, max_chars):
        """A file's text, parts joined (a '## <label>' line before labelled parts), cut at max_chars:
        (text, truncated)."""
        out, size = [], 0
        for p in self.db.execute("SELECT label, block_id, offset, length FROM text_parts WHERE file_id = ? ORDER BY seq",
                                 (file_id,)).fetchall():
            text = self._slice(p)
            piece = ("## %s\n\n%s" % (p["label"], text)) if p["label"] else text
            out.append(piece)
            size += len(piece) + 2
            if size > max_chars:
                break
        text = "\n\n".join(out)
        more = self.db.execute("SELECT COUNT(*) FROM text_parts WHERE file_id = ?", (file_id,)).fetchone()[0] > len(out)
        return text[:max_chars], len(text) > max_chars or more


# Words, and codes that keep their joining characters: MH-3, 12+50, C-104, 2026-10-03, J.Smith (as projectdb.py)
_TOKEN = re.compile(r"[^\W_]+(?:[-+./][^\W_]+)*")


def fts_query(text):
    """What someone typed as an FTS5 query finding every word in any order: each word a quoted term, each code a
    quoted phrase of its pieces ('MH-3 culvert' -> '"MH 3" "culvert"'). '' when there are no words."""
    return " ".join('"' + " ".join(re.findall(r"[^\W_]+", token)) + '"' for token in _TOKEN.findall(text or ""))


# ---------------------------------------------------------------------------
# opening a database (contract: Opening)
# ---------------------------------------------------------------------------
class _Db(sqlite3.Connection):
    """A connection that remembers whether a newer suite tool wrote the database (then it is read only)."""
    too_new = None


def _meta(db, key):
    """A meta value, or None (also for a file without a meta table yet)."""
    try:
        row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    except sqlite3.DatabaseError:
        return None
    return row[0] if row else None


def _set_meta(db, key, value):
    db.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (key, value))


@contextlib.contextmanager
def _write(db):
    """One short write transaction (BEGIN IMMEDIATE ... COMMIT, rolled back on any error). Refused on a database a
    newer suite tool wrote."""
    if db.too_new:
        raise KnowledgeError("This project database was written by a newer version of a suite tool (schema %s; TBC MCP "
                             "knows %d), so TBC MCP only reads it. Ask the user to update TBC MCP." % (db.too_new, SCHEMA_VERSION))
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")


def connect(path, name=None, create=False):
    """Open a job's database with the suite's settings (WAL, 30 s busy timeout, autocommit + explicit transactions).

    create: make the database when it doesn't exist (runs project-db.sql, then sets schema_version, project_id,
            created and project_name). Without it a missing file raises KnowledgeError.
    An old <slug>.json next to it is imported once (import_json_notes). Rows come back as sqlite3.Row.
    """
    exists = os.path.isfile(path)
    if not exists and not create:
        raise KnowledgeError("No project database %s." % path)
    if not exists:
        shared_root()  # moves the pre-2.2.0 folder first, so creating this one can't block that move
        os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(path, timeout=30, isolation_level=None, factory=_Db)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 30000")
        version = _meta(db, "schema_version")
        try:
            newer = version is not None and int(version) > SCHEMA_VERSION
        except ValueError:
            newer = True
        if newer:
            db.too_new = version
            return db  # read as far as we understand it; never written
        db.execute("PRAGMA journal_mode = WAL")
        if version is None:
            with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
                db.executescript(f.read())
            with _write(db):
                if _meta(db, "schema_version") is None:  # another tool may have created it meanwhile
                    _set_meta(db, "schema_version", str(SCHEMA_VERSION))
                    _set_meta(db, "project_id", secrets.token_hex(6))
                    _set_meta(db, "created", _now())
        if name and not _meta(db, "project_name"):
            with _write(db):
                _set_meta(db, "project_name", one_line(name))
        legacy = path[:-len(".db")] + ".json"
        if os.path.exists(legacy):
            import_json_notes(db, legacy)
        return db
    except BaseException:
        db.close()
        raise


def next_id(db, table, prefix):
    """The next free '<prefix>-N' id in `table` (N = highest existing + 1, retired rows included). Call inside the
    write transaction that inserts it."""
    row = db.execute("SELECT MAX(CAST(SUBSTR(id, %d) AS INTEGER)) FROM %s WHERE id GLOB '%s-[0-9]*'"
                     % (len(prefix) + 2, table, prefix)).fetchone()
    return "%s-%d" % (prefix, (row[0] or 0) + 1)


def import_json_notes(db, json_path):
    """Import an old <slug>.json notes file into the database once, then rename it to *.json.imported (contract:
    Moving from the JSON notes files; same behaviour as project-analyzer's projectdb.import_json_notes).

    In one transaction: project_name from "name" (if not set); each folder into `folders` (tool civil3d); each note
    as a new fact with tool = its "source" (missing = civil3d), added/updated kept, sources
    [{"file": "user", "path": "project note"}] and origin {"note_id": "note-N"}. A file that doesn't parse is left
    alone. meta.json_notes_imported stops a second import when the rename fails (file in use); the rename is retried
    on the next open. Returns the number of notes imported.
    """
    done = json_path + ".imported"
    if _meta(db, "json_notes_imported"):
        try:
            os.rename(json_path, done)
        except OSError:
            pass
        return 0
    if db.too_new:
        return 0
    try:
        with open(json_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0
    count = 0
    with _write(db):
        if _meta(db, "json_notes_imported"):
            return 0  # another tool imported it a moment ago
        _set_meta(db, "json_notes_imported", _now())
        if data.get("name") and not _meta(db, "project_name"):
            _set_meta(db, "project_name", str(data["name"]))
        for folder in data.get("folders", []) or []:
            if isinstance(folder, str) and folder.strip():
                db.execute("INSERT OR IGNORE INTO folders(path, tool, added) VALUES (?, 'civil3d', ?)", (folder, _now()))
        for note in data.get("notes", []) or []:
            if not isinstance(note, dict):
                continue
            text = " ".join(str(note.get("note", "")).split())
            if not text:
                continue
            db.execute("INSERT INTO facts(id, fact, sources, tool, origin, added, updated) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (next_id(db, "facts", "fact"), text, json.dumps([{"file": "user", "path": "project note"}]),
                        str(note.get("source") or "civil3d"), json.dumps({"note_id": note.get("id")}),
                        note.get("added") or _now(), note.get("updated")))
            count += 1
    try:
        os.rename(json_path, done)
    except OSError:
        pass
    return count


# ---------------------------------------------------------------------------
# which job: every <slug>.db (and not yet imported <slug>.json), cached by file stamps (contract: Finding the job)
# ---------------------------------------------------------------------------
_index = {}  # file path -> (stamp, job dict or None)


def _stamp(path):
    """What changes when a database (or its WAL file) is written: sizes and modified times."""
    out = []
    for p in (path, path + "-wal"):
        try:
            st = os.stat(p)
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def _read_job_db(path):
    """{name, slug, db, json, roots, folders} of one database, read without writing anything; None when it can't
    be read."""
    try:
        db = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path.replace("\\", "/")), uri=True, timeout=30)
    except sqlite3.Error:
        return None
    try:
        db.execute("PRAGMA busy_timeout = 30000")
        meta = dict(db.execute("SELECT key, value FROM meta WHERE key IN ('project_name', 'source_root')").fetchall())
        folders = [(r[0], r[1]) for r in db.execute("SELECT path, tool FROM folders").fetchall()]
    except sqlite3.Error:
        return None
    finally:
        db.close()
    stem = os.path.basename(path)[:-len(".db")]
    roots = [f for f, _ in folders] + ([meta["source_root"]] if meta.get("source_root") else [])
    return {"name": meta.get("project_name") or stem, "slug": stem, "db": path, "json": None,
            "source_root": meta.get("source_root"), "folders": folders, "roots": roots}


def _read_job_json(path):
    """The same for an old <slug>.json notes file that no database has imported yet; None when it doesn't parse."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    stem = os.path.basename(path)[:-len(".json")]
    folders = [(f, "civil3d") for f in data.get("folders") or [] if isinstance(f, str) and f.strip()]
    return {"name": str(data.get("name") or stem), "slug": stem, "db": path[:-len(".json")] + ".db", "json": path,
            "source_root": None, "folders": folders, "roots": [f for f, _ in folders]}


def job_index(shared=None):
    """Every job in <shared>\\projects: its databases, plus old <slug>.json files without a database yet. Each
    file is read again only when it changed. shared: another shared folder (the repo audit); default the
    configured one. Files that can't be read are skipped, never changed."""
    d = os.path.join(shared, "projects") if shared else projects_dir()
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    jobs, have_db = [], set(n[:-3] for n in names if n.endswith(".db"))
    for n in names:
        if n.endswith(".db"):
            reader = _read_job_db
        elif n.endswith(".json") and n[:-5] not in have_db:
            reader = _read_job_json
        else:
            continue
        path = os.path.join(d, n)
        stamp = _stamp(path)
        cached = _index.get(path)
        if not cached or cached[0] != stamp:
            cached = (stamp, reader(path))
            _index[path] = cached
        if cached[1]:
            jobs.append(cached[1])
    return jobs


def project_for_path(path):
    """The job whose folder (meta.source_root or a `folders` row) contains this file (the open .vce); the deepest
    folder wins across all databases. None for a relative path (an unsaved project) or no match."""
    if not path or not os.path.isabs(path):
        return None
    directory = _key(os.path.dirname(path))
    best, depth = None, -1
    for job in job_index():
        for root in job["roots"]:
            r = _key(root)
            if (directory == r or directory.startswith(r + "\\")) and len(r) > depth:
                best, depth = job, len(r)
    return best


def find_project(name):
    """The job with this name: <slug>.db, else an old <slug>.json, else a database whose project_name matches
    (any case). None when there is none."""
    if not slug(name or ""):
        return None
    jobs = job_index()
    s = slug(name)
    return (next((j for j in jobs if j["slug"] == s), None)
            or next((j for j in jobs if j["name"].strip().lower() == name.strip().lower()), None))


def resolve(name, active_path):
    """The named job, or the one the open TBC project belongs to; KnowledgeError saying what to do otherwise."""
    if name:
        job = find_project(name)
        if not job:
            raise KnowledgeError("No project named %r. Use action=link to create it (or list the known projects with "
                                 "action=list and no project)." % name)
        return job
    job = project_for_path(active_path)
    if not job:
        raise KnowledgeError(
            "The open TBC project%s isn't in a known project folder. Ask the user which job it is, then use "
            "action=link (project, optional folder; default: the open project's folder)."
            % (" (%s)" % os.path.basename(active_path) if active_path else ""))
    return job


@contextlib.contextmanager
def opened(job, create=False):
    """A connection to the job's database (an old JSON-only job is moved into a new database on first open),
    closed afterwards."""
    db = connect(job["db"], job["name"], create=create or bool(job.get("json")))
    try:
        yield db
    finally:
        db.close()
        _index.pop(job["db"], None)
        if job.get("json"):
            _index.pop(job["json"], None)


# ---------------------------------------------------------------------------
# privacy: nothing private goes into the shared database (contract: Ownership and writing, Privacy)
# ---------------------------------------------------------------------------
_private = {}  # lowercased value -> what it is; registered by the server (session token, license fingerprint)


def add_private(value, what):
    """Register a value that must never reach a shared fact (the bridge token, the license fingerprint ...)."""
    if value and len(str(value)) >= 6:
        _private[str(value).lower()] = what


def _private_folders():
    """Per-user folders that never belong in a shared job: AppData, temp, TBC MCP's own."""
    roots = [os.environ.get(v) for v in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "TBC_MCP_USER_DIR")]
    return [_key(r) for r in roots if r]


def _profile():
    """The user's profile folder, normalized and lowercased, for the privacy checks."""
    return _key(os.path.expanduser("~"))


def check_private_text(text):
    """Raise KnowledgeError when text holds a registered private value (bridge session token, license fingerprint)
    or a path inside the user's profile. Used for shared facts and practices, and by knowledge.check_general."""
    low = (text or "").lower().replace("/", "\\")
    found = sorted({what for value, what in _private.items() if value in low})
    if _profile() and _profile() + "\\" in low:
        found.append("a path inside your user profile (write the file name, or the path inside the job folder)")
    if found:
        raise KnowledgeError("Shared project knowledge must not contain %s. It is shared with other tools and people; "
                             "rewrite it without that." % " or ".join(found))


def check_private_folder(folder):
    """Raise KnowledgeError when a folder is the profile root, or inside AppData, temp or TBC MCP's private folder:
    those can never be linked to a shared job."""
    f = _key(folder)
    if f == _profile() or any(f == r or f.startswith(r + "\\") for r in _private_folders()):
        raise KnowledgeError("%s is a private per-user folder (user profile, AppData or temp), so it can't be linked to "
                             "a shared job. Link the job's own folder (drawings, TBC projects, documents)." % folder)


def format_hints(text):
    """Reference-format reminders for a fact (it is still saved: they're advice, not rules)."""
    return sorted({hint for rx, hint in _FORMAT_CHECKS if rx.search(text)})


# ---------------------------------------------------------------------------
# facts
# ---------------------------------------------------------------------------
# Current = not retired and not corrected by a fact that is itself current
_CURRENT = ("f.retired IS NULL AND NOT EXISTS (SELECT 1 FROM facts s WHERE s.supersedes = f.id AND s.retired IS NULL)")


def _fact(row):
    """A facts row as returned to the AI: JSON columns parsed, 'by' = the tool that wrote it, empty fields left out."""
    d = dict(row)
    out = {"id": d["id"], "fact": d["fact"], "by": d["tool"]}
    for k in ("topics", "sources", "conflicts_with", "confirmed_by", "origin"):
        if k in d:
            v = _loads(d[k], None)
            if v:
                out[k] = v
    for k in ("date", "confidence", "supersedes", "author", "added", "updated", "retired"):
        if d.get(k):
            out[k] = d[k]
    if d.get("key"):
        out["key"] = True
    return out


def _facts(db, where="1", args=(), order="f.added DESC, f.id DESC", limit=None):
    sql = "SELECT f.* FROM facts f WHERE %s AND %s ORDER BY %s" % (_CURRENT, where, order)
    if limit:
        sql += " LIMIT %d" % int(limit)
    return [_fact(r) for r in db.execute(sql, args).fetchall()]


def _clean_fact(text):
    """A fact's text made one line and checked for private data; KnowledgeError when it is empty or private."""
    text = one_line(text)
    if not text:
        raise KnowledgeError("The note is empty.")
    check_private_text(text)
    return text


def _with_hints(result, text):
    """Add reference-format reminders to a write result when the fact wasn't written in the suite's formats."""
    hints = format_hints(text)
    if hints:
        result["format_hints"] = ("Saved. Next time use the suite's reference formats so Project Analyzer connects the "
                                  "fact to the same items in documents: %s (%s)." % ("; ".join(hints), REFERENCE_FORMATS))
    return result


def _source(active_path, source):
    """Where TBC learned a fact: the open TBC project ({"file": "tbc:<path>", "path": "<name>.vce"}) or the user.
    A project inside the user's profile is recorded by file name only (no profile paths in shared data)."""
    if source == "user" or not active_path or not os.path.isabs(active_path):
        return {"file": "user", "path": "said by the user"}
    full = os.path.abspath(active_path)
    inside_profile = _key(full).startswith(_profile() + "\\")
    return {"file": "tbc:" + (os.path.basename(full) if inside_profile else full), "path": os.path.basename(full)}


def _options(opts):
    """Checked optional fields of a fact: topics (list of strings), date (YYYY, YYYY-MM, YYYY-MM-DD), key (bool),
    confidence (high, medium, low)."""
    out = {}
    if opts.get("topics") is not None:
        topics = opts["topics"]
        if isinstance(topics, str):
            topics = [topics]
        if not isinstance(topics, list) or not all(isinstance(t, str) for t in topics):
            raise KnowledgeError("topics must be a list of strings, e.g. ['structure:MH-3', 'storm'].")
        out["topics"] = [one_line(t) for t in topics if one_line(t)]
        check_private_text(" ".join(out["topics"]))
    if opts.get("date"):
        if not _DATE.match(str(opts["date"])):
            raise KnowledgeError("date must be YYYY, YYYY-MM or YYYY-MM-DD (e.g. 2026-10-03).")
        out["date"] = str(opts["date"])
    if opts.get("key") is not None:
        out["key"] = 1 if opts["key"] else 0
    if opts.get("confidence"):
        if opts["confidence"] not in ("high", "medium", "low"):
            raise KnowledgeError("confidence must be high, medium or low.")
        out["confidence"] = opts["confidence"]
    return out


def add_note(note, name, active_path, topics=None, date=None, key=None, confidence=None, supersedes=None, source=None):
    """action=add: a new fact owned by TBC (tool 'tbc', id fact-N taken in the same BEGIN IMMEDIATE transaction).

    The same text (any case) among the current facts is not added again: when it is TBC's own fact, this source is
    added to it; another tool's fact is left as it is. supersedes: the id of a fact this one corrects (any tool's).
    source: 'tbc' (seen in the open TBC project, the default when one is open) or 'user' (said by the user).
    """
    text = _clean_fact(note)
    fields = _options({"topics": topics, "date": date, "key": key, "confidence": confidence})
    job = resolve(name, active_path)
    if name and active_path and (project_for_path(active_path) or {}).get("db") != job["db"]:
        active_path = None  # the open TBC project belongs to another job: it isn't this fact's source
    src = _source(active_path, source)
    with opened(job) as db:
        with _write(db):
            for row in db.execute("SELECT f.* FROM facts f WHERE " + _CURRENT).fetchall():
                if row["fact"].strip().lower() != text.lower():
                    continue
                if row["tool"] != TOOL:
                    return {"success": True, "action": "unchanged", "project": job["name"], "fact": _fact(row),
                            "note": "%s already records this; nothing added." % TOOL_LABELS.get(row["tool"], row["tool"])}
                sources = _loads(row["sources"], [])
                if src in sources:
                    return {"success": True, "action": "unchanged", "project": job["name"], "fact": _fact(row)}
                db.execute("UPDATE facts SET sources = ?, updated = ? WHERE id = ?",
                           (json.dumps(sources + [src], ensure_ascii=False), _now(), row["id"]))
                fact = _fact(db.execute("SELECT * FROM facts WHERE id = ?", (row["id"],)).fetchone())
                return {"success": True, "action": "source added", "project": job["name"], "fact": fact}
            if supersedes and not db.execute("SELECT 1 FROM facts WHERE id = ?", (supersedes,)).fetchone():
                raise KnowledgeError("No fact %r to supersede in project %r." % (supersedes, job["name"]))
            fact_id = next_id(db, "facts", "fact")
            db.execute("INSERT INTO facts(id, fact, topics, date, confidence, key, supersedes, sources, tool, added) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (fact_id, text, json.dumps(fields.get("topics", []), ensure_ascii=False), fields.get("date"),
                        fields.get("confidence", "high"), fields.get("key", 0), supersedes or None,
                        json.dumps([src], ensure_ascii=False), TOOL, _now()))
            fact = _fact(db.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone())
    return _with_hints({"success": True, "action": "added", "project": job["name"], "fact": fact,
                        "database": job["db"]}, text)


def _own_fact(db, job, fact_id):
    """The facts row with this id when TBC wrote it and it isn't retired; KnowledgeError otherwise."""
    row = db.execute("SELECT * FROM facts WHERE id = ?", (fact_id or "",)).fetchone()
    if not row:
        raise KnowledgeError("No fact %r in project %r." % (fact_id, job["name"]))
    if row["tool"] != TOOL:
        raise KnowledgeError("%s was written by %s, which owns it. Don't rewrite or remove another tool's facts: add a "
                             "new fact that corrects it (action=add with supersedes=%s)."
                             % (fact_id, TOOL_LABELS.get(row["tool"], row["tool"]), fact_id))
    if row["retired"]:
        raise KnowledgeError("%s was removed on %s." % (fact_id, row["retired"]))
    return row


def update_note(fact_id, note, name, active_path, topics=None, date=None, key=None, confidence=None):
    """action=update: change the text (and optionally topics, date, key, confidence) of one of TBC's own facts and
    stamp 'updated'."""
    text = _clean_fact(note)
    fields = _options({"topics": topics, "date": date, "key": key, "confidence": confidence})
    job = resolve(name, active_path)
    with opened(job) as db:
        with _write(db):
            _own_fact(db, job, fact_id)
            sets, args = ["fact = ?", "updated = ?"], [text, _now()]
            for k, v in fields.items():
                sets.append("%s = ?" % k)
                args.append(json.dumps(v, ensure_ascii=False) if k == "topics" else v)
            db.execute("UPDATE facts SET %s WHERE id = ?" % ", ".join(sets), args + [fact_id])
            fact = _fact(db.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone())
    return _with_hints({"success": True, "action": "updated", "project": job["name"], "fact": fact}, text)


def remove_note(fact_id, name, active_path):
    """action=remove: retire one of TBC's own facts (hidden, kept, its id never reused). Another tool's fact is
    refused; it is corrected by adding one with supersedes."""
    job = resolve(name, active_path)
    with opened(job) as db:
        with _write(db):
            _own_fact(db, job, fact_id)
            db.execute("UPDATE facts SET retired = ? WHERE id = ?", (_now(), fact_id))
            fact = _fact(db.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone())
    return {"success": True, "action": "removed", "project": job["name"], "fact": fact}


# ---------------------------------------------------------------------------
# folders
# ---------------------------------------------------------------------------
def _folders(db):
    """[{path, by}] of the job's folders, the analysed folder (source_root) first."""
    out = []
    root = _meta(db, "source_root")
    if root:
        out.append({"path": root, "by": "project-analyzer", "source_root": True})
    out.extend({"path": r["path"], "by": r["tool"]} for r in db.execute("SELECT path, tool FROM folders ORDER BY added, path"))
    return out


def link(name, folder, active_path):
    """action=link: create a job's database (or open the existing one) and add a folder to it with tool 'tbc'
    (default: the open .vce's folder). A folder already linked by any tool, or the analysed folder, changes
    nothing; private per-user folders are refused."""
    target = folder or (os.path.dirname(active_path) if active_path and os.path.isabs(active_path) else None)
    if not target:
        raise KnowledgeError("No folder given and the open TBC project's folder isn't known (save the project first).")
    if not slug(name or ""):
        raise KnowledgeError("Give the project a name with letters or digits.")
    check_private_folder(target)
    check_private_text(name)
    normalized = normalize_folder(target)
    job = find_project(name)
    created = job is None
    if created:
        path = db_path(name)
        job = {"name": one_line(name), "slug": slug(name), "db": path, "json": None}
    with opened(job, create=created) as db:
        known = [f["path"] for f in _folders(db)]
        if any(_key(f) == _key(normalized) for f in known):
            action = "unchanged"  # already linked (by TBC or another tool): nothing to write
        else:
            with _write(db):
                db.execute("INSERT INTO folders(path, tool, added) VALUES (?, ?, ?)", (normalized, TOOL, _now()))
            action = "created" if created else "linked"
        folders = _folders(db)
        job_name = _meta(db, "project_name") or job["name"]
    return {"success": True, "action": action, "project": job_name, "folders": folders, "database": job["db"],
            "user_knowledge_folder": _ensure_files_dir(job)}


def unlink(name, folder):
    """action=unlink: drop a folder TBC linked itself (never another tool's). The job and its facts stay."""
    if not folder:
        raise KnowledgeError("folder is required")
    job = find_project(name) if name else None
    if not job:
        raise KnowledgeError("No project named %r." % name)
    with opened(job) as db:
        rows = [r for r in db.execute("SELECT path, tool FROM folders").fetchall() if _key(r["path"]) == _key(folder)]
        if not rows:
            raise KnowledgeError("%r isn't a linked folder of %r. Linked: %s." % (
                folder, job["name"], "; ".join(f["path"] for f in _folders(db)) or "(none)"))
        if not any(r["tool"] == TOOL for r in rows):
            raise KnowledgeError("%r was linked by %s, so TBC keeps it: a tool unlinks only the folders it linked itself."
                                 % (folder, TOOL_LABELS.get(rows[0]["tool"], rows[0]["tool"])))
        with _write(db):
            for r in rows:
                if r["tool"] == TOOL:
                    db.execute("DELETE FROM folders WHERE path = ? AND tool = ?", (r["path"], TOOL))
        folders = _folders(db)
    return {"success": True, "action": "unlinked", "project": job["name"], "folders": folders}


# ---------------------------------------------------------------------------
# read actions (contract: What to tell the AI)
# ---------------------------------------------------------------------------
def _count(db, sql, args=()):
    try:
        return db.execute(sql, args).fetchone()[0]
    except sqlite3.DatabaseError:
        return 0


def _missing_files(db):
    """How many distinct referenced paths are missing from the job folder (refs with status missing)."""
    return _count(db, "SELECT COUNT(DISTINCT LOWER(COALESCE(normalized, raw))) FROM refs WHERE status = 'missing'")


def _copy_hint(db):
    """What the AI must know when the job folder is a copy (paths in its files point at the original), or None."""
    copy, roots = _meta(db, "copy_status"), _loads(_meta(db, "reference_roots"), [])
    if not copy and not roots and not _missing_files(db):
        return None
    if copy and copy.strip().lower().startswith("not a copy"):
        return None
    return ("COPIED FOLDER%s: paths written in the job's files - a TBC project's imported files, linked images and "
            "data sources - may still point at the original location. When TBC reports a missing or unresolved file, "
            "or a path the user mentions doesn't exist, use tbc_project_notes action=locate (path) before telling the "
            "user it's missing; never guess." % (" (%s)" % copy if copy else ""))


def _base(job, db):
    out = {"project": _meta(db, "project_name") or job["name"], "database": job["db"]}
    if db.too_new:
        out["read_only"] = ("Written by a newer suite tool (schema %s): TBC MCP reads it but can't change it. Ask the "
                            "user to update TBC MCP." % db.too_new)
    return out


def describe(job, limit=100):
    """action=list for one job: folders, the current facts (newest first, at most `limit`), counts, paths."""
    with opened(job) as db:
        r = _base(job, db)
        total = _count(db, "SELECT COUNT(*) FROM facts f WHERE " + _CURRENT)
        r.update({"folders": _folders(db), "facts": _facts(db, limit=limit), "facts_total": total,
                  "user_knowledge_folder": _ensure_files_dir(job),
                  "hint": "Facts from every tool ('by': tbc, civil3d, project-analyzer). Only TBC's own can be "
                          "updated or removed. For the whole picture use action=overview; to find anything in the "
                          "job's documents use action=search."})
        if total > limit:
            r["more"] = "%d more facts: use action=search (query) to find them." % (total - limit)
        hint = _copy_hint(db)
        if hint:
            r["copied_folder"] = hint
    return r


def list_notes(name, active_path, limit=100):
    """action=list: the named job, or the job the open .vce belongs to. When no job matches, the known jobs and a
    hint to link one."""
    if name:
        return describe(resolve(name, None), limit)
    job = project_for_path(active_path)
    if not job:
        return {"project": None, "open_project": os.path.basename(active_path) if active_path else None,
                "shared_knowledge_dir": shared_root(),
                "known_projects": [{"name": j["name"], "folders": [f for f, _ in j["folders"]],
                                    "source_root": j.get("source_root")} for j in job_index()],
                "hint": "No project is linked to this folder yet. If it's one of the known projects (e.g. analysed by "
                        "Project Analyzer or set up in Civil 3D), link this folder to it; otherwise ask the user for a "
                        "project name. Then action=link."}
    return describe(job, limit)


def overview(name, active_path):
    """action=overview: the job at a glance (contract table): meta, files by status, key facts, the 10 newest facts,
    open questions, rules, checks of severity high, the people in most files, and the suite's practices."""
    job = resolve(name, active_path)
    with opened(job) as db:
        r = _base(job, db)
        for k in ("source_root", "copy_status", "last_run_finished", "source_unchanged"):
            v = _meta(db, k)
            if v:
                r[k] = v
        r["folders"] = _folders(db)
        r["files_by_status"] = {s: n for s, n in db.execute(
            "SELECT status, COUNT(*) FROM files WHERE substr(path, 1, ?) <> ? GROUP BY status ORDER BY COUNT(*) DESC",
            (len(USER_PREFIX), USER_PREFIX)).fetchall()}
        r["key_facts"] = _facts(db, "f.key = 1", limit=50)
        r["newest_facts"] = _facts(db, limit=10)
        r["open_questions"] = [{"id": q["id"], "question": q["question"], "by": q["tool"]} for q in db.execute(
            "SELECT id, question, tool FROM questions WHERE status = 'open' ORDER BY added").fetchall()]
        r["rules"] = [{"id": x["id"], "rule": x["rule"], "by": x["tool"]} for x in db.execute(
            "SELECT id, rule, tool FROM rules WHERE retired IS NULL ORDER BY added, id").fetchall()]
        r["checks_high"] = [{"id": c["id"], "kind": c["kind"], "title": c["title"], "detail": c["detail"]}
                            for c in db.execute("SELECT id, kind, title, detail FROM intel_checks WHERE severity = 'high' "
                                                "ORDER BY id").fetchall()]
        r["people"] = [{"name": p["name"], "aliases": _loads(p["aliases"], []), "files": p["files"]} for p in db.execute(
            "SELECT name, aliases, files FROM intel_entities WHERE type = 'person' ORDER BY files DESC, name LIMIT 15")]
        r["missing_files"] = _missing_files(db)
        r["user_knowledge"] = user_knowledge_summary(job, db)
        hint = _copy_hint(db)
        if hint:
            r["copied_folder"] = hint
    try:
        import practices
        r["practices"] = [{"id": p["id"], "practice": p["practice"]} for p in practices.current()]
    except Exception:
        pass  # practices are advice; a broken practices.json never breaks the overview
    r["hint"] = ("Follow the key facts, rules and the user's own documents (user_knowledge). Before relying on something in checks_high, tell the user. Look things "
                 "up with action=search (words, codes like MH-3 or 12+50), action=entity (a person, structure, sheet, "
                 "RFI), action=file and action=timeline.")
    return r


def _snippet(body, words):
    low = body.lower()
    """About 240 characters around the first place one of the words occurs, starting at a word."""
    at = min((i for i in (low.find(w) for w in words) if i >= 0), default=0)
    start = max(at - 100, 0)
    if start:
        space = body.find(" ", start, at)
        start = space + 1 if space >= 0 else start
    return ("…" if start else "") + " ".join(body[start:start + 240].split())


def search(query, name, active_path, limit=20):
    """action=search: the job's documents through the full-text index (best parts first, with a snippet around
    the first match), plus the current facts containing every word (LIKE on fact and topics)."""
    q = fts_query(query)
    if not q:
        raise KnowledgeError("query is required: words or codes to find, e.g. 'culvert MH-3' or '12+50'.")
    job = resolve(name, active_path)
    words = [w for w in re.findall(r"[^\W_]+", query.lower()) if len(w) > 1] or [query.lower()]
    with opened(job) as db:
        r = _base(job, db)
        try:
            rows = db.execute("SELECT rowid FROM text_search WHERE text_search MATCH ? ORDER BY rank LIMIT ?",
                              (q, int(limit))).fetchall()
        except sqlite3.OperationalError as ex:
            raise KnowledgeError("Search failed (%s); try plain words." % ex)
        blocks, hits = _Blocks(db), []
        for (part_id,) in rows:
            file_id, label, body = blocks.part(part_id)
            f = db.execute("SELECT path, kind, doc_date FROM files WHERE id = ?", (file_id,)).fetchone()
            hit = {"file": file_id, "path": f["path"] if f else None, "part": label, "snippet": _snippet(body, words)}
            if f and f["doc_date"]:
                hit["date"] = f["doc_date"]
            if f and f["path"].startswith(USER_PREFIX):
                hit["user_knowledge"] = True
            hits.append(hit)
        hits += _search_unread(job, db, words, max(int(limit) - len(hits), 0))
        where = " AND ".join(["(f.fact LIKE ? OR f.topics LIKE ?)"] * len(words))
        args = [a for w in words for a in ("%" + w + "%",) * 2]
        r.update({"query": query, "documents": hits, "facts": _facts(db, where, args, limit=int(limit))})
        r["hint"] = ("Open a document with action=file (file=<id or path>); one marked user_knowledge (the user's own "
                     "guidelines and requirements) also with action=read (file=<its path without '<user knowledge>\\'>). "
                     "Codes are matched as phrases (MH-3 finds 'MH 3' and 'MH-3').")
    return r


def _find_file(db, ref):
    """A files row by id, relative path or name (any case); KnowledgeError listing candidates when it isn't one."""
    ref = (ref or "").strip()
    if not ref:
        raise KnowledgeError("file is required: a file id, or its path in the job folder (e.g. Documents\\specs.pdf).")
    row = db.execute("SELECT * FROM files WHERE id = ?", (ref.lower(),)).fetchone()
    if row:
        return row
    rel = ref.replace("/", "\\")
    root = _meta(db, "source_root")
    if root and _key(rel).startswith(_key(root) + "\\"):
        rel = os.path.abspath(rel)[len(normalize_folder(root)) + 1:]
    for col in ("path", "name"):
        rows = db.execute("SELECT * FROM files WHERE %s = ? COLLATE NOCASE ORDER BY depth, path" % col, (rel,)).fetchall()
        if len(rows) == 1:
            return rows[0]
        if rows:
            raise KnowledgeError("%r matches several files: %s. Give the path or id." % (ref, "; ".join(
                "%s (%s)" % (x["path"], x["id"]) for x in rows[:10])))
    like = db.execute("SELECT id, path FROM files WHERE path LIKE ? ORDER BY depth, path LIMIT 10",
                      ("%" + rel + "%",)).fetchall()
    raise KnowledgeError("No file %r in the project database.%s" % (ref, (" Did you mean: %s?" % "; ".join(
        "%s (%s)" % (x["path"], x["id"]) for x in like)) if like else " Use action=search to find it."))


def file_info(ref, name, active_path, max_chars=FILE_TEXT_CHARS):
    """action=file: one file of the job: its files row, details (props), the latest summary, references from and
    to it, the facts citing it and the first part of its text."""
    job = resolve(name, active_path)
    with opened(job) as db:
        r = _base(job, db)
        f = _find_file(db, ref)
        info = {k: f[k] for k in f.keys() if f[k] is not None}
        props = {}
        for p in db.execute("SELECT key, value FROM props WHERE file_id = ? ORDER BY key", (f["id"],)):
            props.setdefault(p["key"], []).append(p["value"])
        s = db.execute("SELECT summary, points, people, dates, tool FROM summaries WHERE file_id = ? ORDER BY id DESC "
                       "LIMIT 1", (f["id"],)).fetchone()
        refs_from = [{k: x[k] for k in ("kind", "raw", "location", "status", "target_path", "expected_path") if x[k]}
                     for x in db.execute("SELECT * FROM refs WHERE file_id = ? LIMIT 200", (f["id"],))]
        refs_to = [{"from": x["path"], "kind": x["kind"], "location": x["location"]} for x in db.execute(
            "SELECT r.kind, r.location, g.path FROM refs r LEFT JOIN files g ON g.id = r.file_id WHERE r.target_id = ? "
            "LIMIT 200", (f["id"],))]
        text_id = f["duplicate_of"] if f["status"] == "duplicate" and f["duplicate_of"] else f["id"]
        try:
            text, truncated = _Blocks(db).file_text(text_id, int(max_chars))
        except KnowledgeError as ex:
            text, truncated = None, False
            r["text_error"] = str(ex)
        r.update({"file": info, "props": {k: v[0] if len(v) == 1 else v for k, v in props.items()},
                  "refs_from": refs_from, "refs_to": refs_to,
                  "facts": _facts(db, "f.sources LIKE ?", ('%"' + f["id"] + '"%',))})
        if s:
            r["summary"] = {"summary": s["summary"], "points": _loads(s["points"], []), "people": _loads(s["people"], []),
                            "dates": _loads(s["dates"], []), "by": s["tool"]}
        if text is not None:
            r["text"] = text
            if truncated:
                r["truncated"] = True
            if text_id != f["id"]:
                r["text_from"] = "the same content stored as %s" % text_id
        root = _meta(db, "source_root")
        if root and f["depth"] == 0:
            r["absolute"] = os.path.join(root, f["path"])
    return r


def entity(ref, name, active_path, limit=50):
    """action=entity: a person, organization, place, structure, station, sheet or document number from Project
    Analyzer's connections, by name or alias (any case): its files, events, stories and the facts whose topics name
    it."""
    ref = one_line(ref)
    if not ref:
        raise KnowledgeError("name is required: e.g. 'John Smith', 'MH-3', 'C-104', 'RFI 12'.")
    job = resolve(name, active_path)
    low = ref.lower()
    with opened(job) as db:
        r = _base(job, db)
        cands = db.execute("SELECT * FROM intel_entities WHERE name LIKE ? OR aliases LIKE ? ORDER BY files DESC",
                           ("%" + ref + "%", "%" + ref + "%")).fetchall()
        exact = [c for c in cands if (c["name"] or "").lower() == low
                 or any(str(a).lower() == low for a in _loads(c["aliases"], []))]
        if not exact:
            r["found"] = False
            r["similar"] = [{"name": c["name"], "type": c["type"], "files": c["files"]} for c in cands[:15]]
            r["facts"] = _facts(db, "(f.topics LIKE ? OR f.fact LIKE ?)", ("%" + ref + "%",) * 2, limit=limit)
            r["hint"] = "No entity with that exact name or alias. Try one of 'similar', or action=search."
            return r
        e = exact[0]
        names = [e["name"]] + [str(a) for a in _loads(e["aliases"], [])]
        files = db.execute("SELECT f.id, f.path, f.doc_date, ef.count FROM intel_entity_files ef JOIN files f ON "
                           "f.id = ef.file_id WHERE ef.entity_id = ? ORDER BY ef.count DESC, f.path LIMIT ?",
                           (e["id"], int(limit))).fetchall()
        ids = [f["id"] for f in files]
        # its events: those of the files it appears in, and those whose title names it
        cond = ["e.title LIKE ?"] * len(names) + (["e.file_id IN (%s)" % ",".join("?" * len(ids))] if ids else [])
        events = db.execute("SELECT e.date, e.kind, e.title, g.path FROM intel_events e LEFT JOIN files g ON "
                            "g.id = e.file_id WHERE %s ORDER BY e.date LIMIT ?" % " OR ".join(cond),
                            ["%" + n + "%" for n in names] + ids + [int(limit)]).fetchall()
        scond = " OR ".join(["title LIKE ? OR subject LIKE ? OR refs LIKE ? OR people LIKE ?"] * len(names))
        stories = []
        for s in db.execute("SELECT * FROM intel_stories WHERE %s ORDER BY first_date LIMIT 20" % scond,
                            [x for n in names for x in ("%" + n + "%",) * 4]).fetchall():
            steps = [{"date": st["date"], "kind": st["kind"], "who": st["who"], "what": st["what"]} for st in db.execute(
                "SELECT * FROM intel_story_steps WHERE story_id = ? ORDER BY position LIMIT 30", (s["id"],))]
            stories.append({"id": s["id"], "title": s["title"], "first_date": s["first_date"], "last_date": s["last_date"],
                            "people": _loads(s["people"], []), "amounts": _loads(s["amounts"], []), "steps": steps})
        fcond = " OR ".join(["f.topics LIKE ?"] * len(names))
        r.update({"found": True, "entity": {"name": e["name"], "type": e["type"], "aliases": _loads(e["aliases"], []),
                                            "files": e["files"], "mentions": e["mentions"], "first_date": e["first_date"],
                                            "last_date": e["last_date"], "related": _loads(e["related"], [])},
                  "files": [{"file": f["id"], "path": f["path"], "date": f["doc_date"], "mentions": f["count"]} for f in files],
                  "events": [{"date": x["date"], "kind": x["kind"], "title": x["title"], "path": x["path"]} for x in events],
                  "stories": stories,
                  "facts": _facts(db, "(%s)" % fcond, ["%" + n + "%" for n in names], limit=limit)})
    return r


def timeline(name, active_path, date_from=None, date_to=None, limit=200):
    """action=timeline: Project Analyzer's events plus the dated current facts, in date order, optionally between
    two dates (YYYY, YYYY-MM or YYYY-MM-DD; both ends included)."""
    for d in (date_from, date_to):
        if d and not _DATE.match(str(d)):
            raise KnowledgeError("from and to must be YYYY, YYYY-MM or YYYY-MM-DD.")
    lo, hi = date_from or "", (date_to or "9999") + "\uffff"
    job = resolve(name, active_path)
    with opened(job) as db:
        r = _base(job, db)
        items = [{"date": e["date"], "kind": e["kind"], "title": e["title"], "path": e["path"], "from": "documents"}
                 for e in db.execute("SELECT e.date, e.kind, e.title, g.path FROM intel_events e LEFT JOIN files g ON "
                                     "g.id = e.file_id WHERE e.date >= ? AND e.date <= ?", (lo, hi)).fetchall()]
        items += [{"date": f["date"], "kind": "fact", "title": f["fact"], "fact": f["id"], "by": f["by"]}
                  for f in _facts(db, "f.date IS NOT NULL AND f.date >= ? AND f.date <= ?", (lo, hi))]
        items.sort(key=lambda x: (x["date"] or "", x["title"] or ""))
        r["events"] = items[:int(limit)]
        if len(items) > int(limit):
            r["more"] = "%d more: narrow it with from / to." % (len(items) - int(limit))
    return r


# ---------------------------------------------------------------------------
# copied job folders: where a path written in the job's files is in the copy (contract: Copied job folders)
# ---------------------------------------------------------------------------
def to_windows(raw):
    """A path as Project Analyzer normalizes references: 'file:///P:/Jobs/1234%20Elm/x.pdf' ->
    'P:\\Jobs\\1234 Elm\\x.pdf'; forward slashes -> backslashes; quotes trimmed."""
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


def _in_copy(root, relative):
    """(absolute path, exists) for a path relative to source_root; (None, False) without a root."""
    if not root or relative is None:
        return None, False
    full = os.path.normpath(os.path.join(root, to_windows(relative))) if relative else normalize_folder(root)
    return full, os.path.exists(full)


_STATUS_ORDER = {"found": 0, "found by name": 1, "ambiguous": 2, "missing": 3}


def locate(path, name, active_path):
    """action=locate: where a path as TBC or a file shows it is in the job's copy. refs.normalized first (its
    target_path and status), then meta.reference_roots (original -> source_root\\in_copy), then nothing: never
    guesses."""
    if not path or not str(path).strip():
        raise KnowledgeError("path is required: the file path as TBC or a file shows it")
    job = resolve(name, active_path)
    written = to_windows(str(path))
    record = ("If the user confirms this (or relinks the file in TBC), offer to record it as a fact, asking first, e.g. "
              "'Imported file <path as written> is <path in the copy> in the copy'.")
    with opened(job) as db:
        r = _base(job, db)
        root = _meta(db, "source_root")
        r.update({"path": str(path), "normalized": written, "source_root": root})
        copy = _meta(db, "copy_status")
        if copy:
            r["copy_status"] = copy
        rows = db.execute("SELECT r.*, g.path AS from_path FROM refs r LEFT JOIN files g ON g.id = r.file_id "
                          "WHERE r.normalized = ? COLLATE NOCASE OR r.raw = ? COLLATE NOCASE", (written, str(path))).fetchall()
        if rows:
            best = sorted(rows, key=lambda x: _STATUS_ORDER.get((x["status"] or "").lower(), 9))[0]
            status = (best["status"] or "unknown").lower()
            r.update({"source": "refs", "status": status, "times_referenced": len(rows),
                      "referenced_by": sorted({x["from_path"] for x in rows if x["from_path"]})[:10]})
            if best["target_path"]:
                full, exists = _in_copy(root, best["target_path"])
                r.update({"relative": best["target_path"], "absolute": full, "exists": exists})
                if not root:
                    r["note"] = "The project database has no source_root, so only the relative path is known."
                elif not exists:
                    r["note"] = ("The job folder (%s) isn't reachable from this computer, or the file was moved since the "
                                 "analysis." % root)
            if status == "missing":
                if best["expected_path"]:
                    where, _ = _in_copy(root, best["expected_path"])
                    r["expected_at"] = {"relative": best["expected_path"], "absolute": where}
                r["hint"] = ("Not in the job folder. It belongs at %s. Ask the user for the file; don't point TBC at "
                             "another file." % (best["expected_path"] or "a place Project Analyzer could not tell"))
            elif status == "ambiguous":
                r["candidates"] = _loads(best["candidates"], [])
                r["hint"] = "More than one file in the copy could be this one. Ask the user which is right - don't pick one."
            elif status == "found by name":
                r["hint"] = "Matched by file name only, elsewhere in the copy: check with the user that it's the right file. " + record
            else:
                r["hint"] = record
            return r
        low = written.lower()
        originals = []
        for o in _loads(_meta(db, "reference_roots"), []):
            if isinstance(o, dict) and isinstance(o.get("original"), str) and o["original"].strip():
                originals.append((to_windows(o["original"]), to_windows(str(o.get("in_copy") or ""))))
        originals.sort(key=lambda o: -len(o[0]))  # the most specific original folder wins
        for original, in_copy in originals:
            o = original.lower().rstrip("\\")
            if low == o or low.startswith(o + "\\"):
                rest = written[len(o):].lstrip("\\")
                relative = ntpath.join(in_copy, rest) if in_copy and in_copy != "." else rest
                full, exists = _in_copy(root, relative)
                r.update({"source": "reference_roots", "original_folder": original, "relative": relative,
                          "absolute": full, "exists": exists, "status": "translated" if exists else "translated, not found"})
                if not root:
                    r["note"] = "The project database has no source_root, so only the relative path is known."
                r["hint"] = (record if exists else
                             "Under the original folder %s, so in the copy it would be %s - but no file is there. It may "
                             "not have been copied: ask the user for it." % (original, full or relative))
                return r
        r.update({"status": "not known", "source": None,
                  "hint": "Neither the job's references nor its original locations cover this path, so where it is in the "
                          "copy isn't known. Don't guess: ask the user where the original project folder was (or where "
                          "this file is now)."})
        if not originals and not _count(db, "SELECT COUNT(*) FROM refs"):
            r["note"] = ("Project Analyzer hasn't analysed this job's references yet: the user can run it, or tell you "
                         "where the original folder was.")
    try:
        if os.path.isabs(written) and os.path.exists(written):
            r["exists_as_written"] = True
            r["note"] = ((r.get("note", "") + " ").lstrip() + "A file does exist at that path, but it isn't known to be "
                         "this job's copy of it: check with the user before using it.")
    except (OSError, ValueError):
        pass
    return r


# ---------------------------------------------------------------------------
# the job's user knowledge: <shared>\projects\<slug>\User Knowledge\ (the user's own documents for the job:
# guidelines, requirements, standards). Contract: "User knowledge (per job)". Read, never changed; Project Analyzer,
# when installed, reads it into the database as files rows under USER_PREFIX.
# ---------------------------------------------------------------------------
def list_files(directory, limit=500, skip=None):
    """Files under a folder: relative path, size and UTC modified time, sorted, at most `limit`. `skip`: a
    subfolder name (any case) left out at the top level. Returns (files, truncated)."""
    files, truncated = [], False
    if os.path.isdir(directory):
        for dp, dns, fns in os.walk(directory):
            if skip and dp == directory:
                dns[:] = [d for d in dns if d.lower() != skip.lower()]
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


def user_knowledge_dir(job):
    """<shared>\\projects\\<slug>\\User Knowledge for a job (next to its database)."""
    return os.path.join(os.path.splitext(job["db"])[0], USER_KNOWLEDGE_FOLDER)


def _ensure_files_dir(job):
    """The job's User Knowledge folder, created (empty) when missing: the only thing any tool writes there."""
    d = user_knowledge_dir(job)
    os.makedirs(d, exist_ok=True)
    return d


def _epoch(text):
    """Whole seconds since 1970 of an ISO time ('...Z' or '...+00:00'); None when it isn't one."""
    try:
        return int(datetime.datetime.fromisoformat((text or "").replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _analyzer_docs(db):
    """{lower-case path relative to User Knowledge: files row} of the user-knowledge documents in the database."""
    rows = db.execute("SELECT id, path, size, mtime, status, duplicate_of, chars FROM files WHERE depth = 0 AND "
                      "substr(path, 1, ?) = ?", (len(USER_PREFIX), USER_PREFIX)).fetchall()
    return {r["path"][len(USER_PREFIX):].lower(): r for r in rows}


def _fresh(row, full):
    """The database row when Project Analyzer read this very version of the file (same size and modified time,
    with text), else None."""
    if not row or row["status"] not in ("done", "partial", "duplicate"):
        return None
    st = os.stat(full)
    if row["size"] != st.st_size or _epoch(row["mtime"]) != int(st.st_mtime):
        return None
    return row


def _readable_here(full):
    """True when TBC MCP can read the file itself: a text format, or Word / Excel / PowerPoint (.docx .xlsx .pptx)."""
    ext = os.path.splitext(full)[1].lower()
    if ext in TEXT_EXTENSIONS or ext in office_text.EXTENSIONS:
        return True
    if ext in BINARY_EXTENSIONS:
        return False
    try:
        with open(full, "rb") as f:
            return b"\0" not in f.read(4096)
    except OSError:
        return False


def _direct_text(full, limit):
    """Text of a file TBC can read itself (at most `limit` characters are needed; more may be returned)."""
    if os.path.splitext(full)[1].lower() in office_text.EXTENSIONS:
        try:
            return office_text.read(full)
        except office_text.OfficeTextError as ex:
            raise KnowledgeError("%s couldn't be read (%s)." % (os.path.basename(full), ex))
    with open(full, "rb") as f:
        raw = f.read(int(limit) * 4 + 1)
    return raw.decode("utf-8-sig", errors="replace")


def _legacy_files(job):
    """Files put directly in <slug>\\ by versions before User Knowledge (not read; listed so they can be moved)."""
    files, _ = list_files(os.path.splitext(job["db"])[0], limit=100, skip=USER_KNOWLEDGE_FOLDER)
    return [f["path"] for f in files]


def _cant_read(job, rel, full):
    return KnowledgeError(
        "%s can't be read by TBC MCP (it reads text files and Word, Excel and PowerPoint files). Project Analyzer reads "
        "PDFs, scans, drawings and older Office files into the job's database: python analyze.py knowledge --project "
        "\"%s\". Or open the file with your AI app: %s" % (rel, job["name"], full))


def user_knowledge_summary(job, db, limit=30):
    """For overview: the folder, how many documents, their names (at most `limit`), how many the analyzer read."""
    d = _ensure_files_dir(job)
    files, truncated = list_files(d)
    docs = _analyzer_docs(db)
    read = sum(1 for f in files if _fresh(docs.get(f["path"].lower()), os.path.join(d, f["path"])))
    out = {"folder": d, "documents": len(files) if not truncated else "%d+" % len(files),
           "names": [f["path"] for f in files[:limit]], "read_by_analyzer": read}
    out["hint"] = ("The user's own documents for this job (guidelines, requirements, standards). When one applies to "
                   "the task, follow it and name it; when it conflicts with a fact, a practice or the project, tell the "
                   "user rather than choose. action=read opens one, action=search searches them with the job's "
                   "documents." if files else
                   "Empty. The user can put guidelines, requirements for the building type, standards or code books "
                   "for this job here (subfolders are fine).")
    return out


def project_files(name, active_path):
    """action=files: the documents in the job's User Knowledge folder, each with whether Project Analyzer has read
    this version into the database and whether TBC can read it itself."""
    job = resolve(name, active_path)
    d = _ensure_files_dir(job)
    files, truncated = list_files(d)
    with opened(job) as db:
        docs = _analyzer_docs(db)
    for f in files:
        full = os.path.join(d, f["path"])
        f["read_by_analyzer"] = bool(_fresh(docs.get(f["path"].lower()), full))
        f["readable_here"] = f["read_by_analyzer"] or _readable_here(full)
    r = {"project": job["name"], "user_knowledge_folder": d, "files": files, "truncated": truncated,
         "hint": "Empty. The user can put guidelines, requirements for the building type, standards or code books for "
                 "this job here (subfolders are fine). The job's own documents are in the project database: "
                 "action=search / file." if not files else
                 "The user's own documents for this job. Open one with action=read (file=<path as listed>); follow it "
                 "when it applies and name it. The job's own documents are in the project database: action=search / file."}
    legacy = _legacy_files(job)
    if legacy:
        r["elsewhere"] = legacy
        r["elsewhere_hint"] = ("These files are directly in %s, outside User Knowledge, so they aren't read. Suggest the "
                               "user moves them into %s." % (os.path.dirname(d), d))
    return r


def read_file(rel, name, active_path, max_chars=MAX_READ_CHARS, offset=0):
    """action=read: one document of the job's User Knowledge folder (paths outside it are refused): the text Project
    Analyzer stored for this version of it, else read directly (text, .docx, .xlsx, .pptx). `offset` (characters)
    continues a long document where the last read stopped."""
    if not rel:
        raise KnowledgeError("file is required (a path as listed by action=files)")
    job = resolve(name, active_path)
    d = os.path.realpath(_ensure_files_dir(job))
    full = os.path.realpath(os.path.join(d, rel))
    try:
        inside = os.path.commonpath([d, full]).lower() == d.lower()
    except ValueError:  # another drive
        inside = False
    if not inside:
        raise KnowledgeError("Only files inside the job's User Knowledge folder can be read. For the job's documents "
                             "use action=file.")
    if not os.path.isfile(full):
        raise KnowledgeError("No file %r in %s. Use action=files to list them (or action=file for the job's documents)."
                             % (rel, d))
    rel = os.path.relpath(full, d)
    max_chars, offset = int(max_chars), max(int(offset or 0), 0)
    with opened(job) as db:
        row = _fresh(_analyzer_docs(db).get(rel.lower()), full)
        if row:
            text_id = row["duplicate_of"] if row["status"] == "duplicate" and row["duplicate_of"] else row["id"]
            text, more = _Blocks(db).file_text(text_id, offset + max_chars)
            source = "the project database (read by Project Analyzer)"
    if not row:
        if not _readable_here(full):
            raise _cant_read(job, rel, full)
        text = _direct_text(full, offset + max_chars)
        # a plain file is read only as far as needed (4 bytes per character at most)
        more = len(text) > offset + max_chars or (os.path.splitext(full)[1].lower() not in office_text.EXTENSIONS
                                                   and os.path.getsize(full) > (offset + max_chars) * 4 + 1)
        source = "the file"
    r = {"project": job["name"], "file": rel, "size": os.path.getsize(full), "read_from": source,
         "text": text[offset:offset + max_chars]}
    if offset:
        r["offset"] = offset
    if more or len(text) > offset + max_chars:
        r["truncated"] = True
        r["next_offset"] = offset + max_chars
    return r


def _search_unread(job, db, words, limit):
    """Hits in User Knowledge documents the database doesn't have (or has an older version of) that TBC can read."""
    d = _ensure_files_dir(job)
    files, _ = list_files(d, limit=MAX_SCAN_FILES)
    docs, hits = _analyzer_docs(db), []
    for f in files:
        full = os.path.join(d, f["path"])
        if len(hits) >= limit or f["size"] > MAX_SCAN_BYTES or _fresh(docs.get(f["path"].lower()), full) \
                or not _readable_here(full):
            continue
        try:
            text = _direct_text(full, MAX_SCAN_BYTES)
        except (KnowledgeError, OSError):
            continue
        low = text.lower()
        if all(w in low for w in words):
            hits.append({"file": None, "path": USER_PREFIX + f["path"], "user_knowledge": True,
                         "not_in_database": True, "snippet": _snippet(text, words)})
    return hits


# ---------------------------------------------------------------------------
# once per job and server run: a short overview attached to the first result of a session
# ---------------------------------------------------------------------------
_announced = set()


def notes_once(active_path):
    """What the first result of a session carries for the open job: key facts, TBC's own facts, checks of severity
    high and the number of missing referenced files. None when there's nothing to show, when this job was already
    announced in this server run, or on any error (project knowledge is advice and never breaks a call)."""
    try:
        job = project_for_path(active_path)
        if not job or job["db"] in _announced:
            return None
        with opened(job) as db:
            facts = _count(db, "SELECT COUNT(*) FROM facts f WHERE " + _CURRENT)
            files = _count(db, "SELECT COUNT(*) FROM files WHERE substr(path, 1, ?) <> ?", (len(USER_PREFIX), USER_PREFIX))
            user_docs, _ = list_files(user_knowledge_dir(job), limit=31)
            checks = [{"id": c["id"], "title": c["title"]} for c in db.execute(
                "SELECT id, title FROM intel_checks WHERE severity = 'high' ORDER BY id LIMIT 10").fetchall()]
            if not facts and not files and not checks and not user_docs:
                return None
            _announced.add(job["db"])
            r = {"project": _meta(db, "project_name") or job["name"], "facts": facts, "files": files,
                 "key_facts": [{"id": f["id"], "fact": f["fact"], "by": f["by"]} for f in _facts(db, "f.key = 1", limit=15)],
                 "tbc_facts": [{"id": f["id"], "fact": f["fact"]} for f in _facts(db, "f.tool = ?", (TOOL,), limit=20)],
                 "checks_high": checks,
                 "checks_high_total": _count(db, "SELECT COUNT(*) FROM intel_checks WHERE severity = 'high'"),
                 "missing_files": _missing_files(db),
                 "user_knowledge": [f["path"] for f in user_docs[:30]],
                 "hint": "The job's shared project database (also used by Civil 3D MCP and Project Analyzer). Follow "
                         "these facts and the user's own documents for the job (user_knowledge: guidelines, "
                         "requirements; tbc_project_notes action=read opens one); mention checks_high that bear on the task. More: tbc_project_notes "
                         "action=overview / search / entity / file / timeline. Add what you learn about this job with "
                         "action=add (ask the user first), in the suite's reference formats: %s." % REFERENCE_FORMATS}
            hint = _copy_hint(db)
            if hint:
                r["copied_folder"] = hint
            return r
    except Exception:
        return None


def reset_announcements():
    """For tests."""
    _announced.clear()
