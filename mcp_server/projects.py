# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Project knowledge shared with civil3d-mcp-unified and project-analyzer: one SQLite database per job for the suite.

The contract all three follow is project-analyzer's docs/suite-knowledge.md; the exact table layout is its
schema/project-db.sql, shipped here as mcp_server/project-db.sql (a byte-for-byte copy: tests/test_project_knowledge.py
checks it against the SHA-256 recorded there, and against the analyzer's file when that repository is next to this
one). In short:

    <shared>\\projects\\<slug>.db      everything about one job: the analyzer's files, text (zstd-compressed),
                                       references, automatic findings (intel_*), and the facts every tool learned
    <shared>\\projects\\<slug>.backups\\   checked copies of it (Project Analyzer's, and TBC's own daily one below)
    <shared>\\projects\\<slug>\\User Knowledge\\   the user's own documents for the job (guidelines, requirements,
                                       standards); only read (Project Analyzer reads them into the database too)
    <shared>\\practices.json           good practices of the whole suite (practices.py)

<shared> is the suite's folder, found the same way by all three tools (knowledge.shared_dir): PROJECT_KNOWLEDGE_DIR,
else Documents\\Project Knowledge, or an earlier folder (Documents\\Civil3DMcp-KnowledgeBase) used as it is.

What TBC does with it:
  - finds the job of the open .vce: meta.source_root and every `folders` row, across all <shared>\\projects\\*.db,
    case-insensitive on normalized absolute paths, the deepest folder wins (job_index: the list kept INDEX_TTL
    seconds, each database re-read only when its file stamps change; a damaged one is listed with a note)
  - reads: overview, search (full-text index + facts), file, entity, timeline, locate (copied job folders), latest
    (newest version of a file), checks, changes, list, and the job's user knowledge (files, read; also in overview
    and search): the analyzer's stored text when it read that version of a document, else the file itself (text,
    .docx, .xlsx, .pptx via office_text.py)
  - every read opens the database read only (SQLite URI mode=ro): it never runs the schema, switches the journal or
    imports a JSON file, so a read can't change the file
  - works with no other suite tool installed: creates the database and the User Knowledge folder when needed
  - writes only its own rows: facts with tool='tbc' (add with a duplicate check and fact-N taken inside a
    BEGIN IMMEDIATE transaction; update; remove = set `retired`, nothing is deleted) and folders with tool='tbc'
    (link / unlink). Another tool's fact is corrected by adding one with `supersedes` set to it.
  - creates the database when the user links a new job (runs project-db.sql, sets schema_version, project_id,
    created, project_name), and imports an old <slug>.json notes file once, on the first write (import_json_notes,
    as the contract says); until then a read builds the notes in memory from the JSON file
  - a writable open adds the schema's indexes ("CREATE INDEX IF NOT EXISTS" lines) to an older database
  - never writes to a database whose meta.schema_version is newer than it knows (reads it as far as it can), nor to
    a damaged one (PRAGMA quick_check not ok, or an unreadable meta): it says so and how to restore a backup
  - before the first write of a day to a database no analyzer looks after (meta.source_root empty), a checked copy
    goes into <slug>.backups\\ in Project Analyzer's naming; the newest BACKUPS_KEPT are kept
  - privacy: no license details, session tokens or user-profile paths in facts or folders
  - never keeps a copy of a job's files; text is read from the database, decompressed in memory

Connections use autocommit (isolation_level=None) and explicit BEGIN IMMEDIATE ... COMMIT for writes, so two tools
(an 8-hour analyzer run and this server adding a fact) share the file: WAL journal, a BUSY_TIMEOUT busy timeout and
one retry; still busy, the AI is told to try again in a moment.
"""
import collections
import contextlib
import datetime
import fnmatch
import functools
import json
import ntpath
import os
import re
import secrets
import sqlite3
import time
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
# The job's other folders (contract: "More than one folder per job"): meta job_folders [{"name", "path"}]; their files'
# paths start with "<job folder: NAME>\\". on_disk gives any stored path's place on this computer.
FOLDER_PREFIX = "<job folder: "
MAX_SCAN_FILES, MAX_SCAN_BYTES = 200, 20 * 1024 * 1024   # search: documents not in the database, read directly
FILE_TEXT_CHARS = 4000                # action=file: the first part of a file's text
TOOL_LABELS = {"civil3d": "Civil 3D MCP", "project-analyzer": "Project Analyzer", TOOL: "TBC MCP"}
BUSY_TIMEOUT = 10.0                   # seconds SQLite waits for another tool's write (module variables: tests shorten them)
BUSY_RETRY_DELAY = 0.5                # still busy: the action is tried once more after this pause
BUSY_MESSAGE = ("The job's database is busy (Project Analyzer is probably writing to it); try again in a moment.")
INDEX_TTL = 60                        # seconds the list of jobs is kept before <shared>\projects is looked at again
BACKUPS_KEPT = 3                      # TBC's daily copies of a database no analyzer looks after (Project Analyzer's KEEP)
LONG_PATH = 240                       # absolute paths this long are opened in their \\?\ form (past Windows' MAX_PATH)
TEXT_CACHE_CHARS = 64 * 1024 * 1024   # search: text of User Knowledge documents kept in memory between searches

# How every tool in the suite writes references, so Project Analyzer's automatic connections tie a fact to the same
# items in documents and drawings (contract: Reference formats)
REFERENCE_FORMATS = ("dates 2026-10-03; stations 12+50 (12+50.25 only when decimals matter); structures MH-3, CB-12, "
                     "FES-1; sheets C-104; documents RFI 12, CO 4, PCO 7, Submittal 3, ASI 2, Addendum 1, Pay App 5; "
                     "amounts $12,500.00; people by full name, then initials if the files use them: John Smith (J. Smith)")
# The suite's rule for the job database (contract: Reference only), on every read answer with the date it describes.
# Its stored text, coordinates and quantities are a snapshot of the job folder: for finding things, never for edits.
REFERENCE_ONLY = ("Reference only: the job database is a snapshot of the job's files as of %s, and they may have "
                  "changed since. Use it to find and understand things (what a file says, where it is, who did what, "
                  "when). Never use its coordinates, elevations, points, stations, dimensions, quantities or text as "
                  "data to edit or import into a drawing or TBC project: take them from the current source file the "
                  "user names, and if they haven't named one, ask which file is current.")
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


def job_folders(db):
    """The job's other folders (meta job_folders): [{"name", "path"}], [] when none or unreadable."""
    folders = _loads(_meta(db, "job_folders"), [])
    return [f for f in folders if isinstance(f, dict) and f.get("name") and f.get("path")] if isinstance(folders, list) else []


def on_disk(db, relative):
    """Where a top-level file (its files.path) is on this computer: an extra job folder's path + the rest for
    "<job folder: NAME>\\rest", else source_root + the path; None for user knowledge, Outlook emails, or a folder
    the database doesn't know (contract: "More than one folder per job")."""
    relative = to_windows(relative or "")
    if relative.startswith(FOLDER_PREFIX):
        name, _, rest = relative[len(FOLDER_PREFIX):].partition(">\\")
        for folder in job_folders(db):
            if folder["name"].lower() == name.lower():
                return ntpath.join(folder["path"], rest)
        return None
    root = _meta(db, "source_root")
    if relative.startswith("<") or not root:
        return None
    return ntpath.join(root, relative) if relative else root


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
# What search, read and file say when they can't show stored text (they still return everything else)
ZSTD_MISSING = ("The job's text is stored zstd-compressed and the zstandard package isn't installed: install zstandard "
                "(py -3.12 -m pip install zstandard, then restart the AI app) to read the stored text.")


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
        raise KnowledgeError(ZSTD_MISSING)
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

    def parts(self, part_ids):
        """{part id: text_parts row (file_id, label, block_id, offset, length)} of several parts, in one query."""
        ids = list(part_ids)
        if not ids:
            return {}
        return {p["id"]: p for p in self.db.execute(
            "SELECT id, file_id, label, block_id, offset, length FROM text_parts WHERE id IN (%s)" % ",".join("?" * len(ids)),
            ids).fetchall()}

    def text(self, p):
        """The text of one text_parts row (KnowledgeError when its block can't be decompressed here)."""
        return self._slice(p)

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
    """A connection that remembers what it was opened for: its file (path; None in memory), whether it may write
    (writable: link and the note-writing actions), whether TBC just created it, and whether a newer suite tool wrote
    the database (too_new: then it is read only)."""
    too_new = None
    path = None
    writable = False
    created = False
    memory = False     # an old JSON-only job read into memory (nothing on disk yet)
    missing = None     # _missing_files, counted once per connection


def _uri(path):
    """A read-only SQLite URI for a database file (drive and UNC paths; '?', '#' and '%' quoted)."""
    p = os.path.abspath(path).replace("\\", "/")
    return "file:%s%s?mode=ro" % ("//" if p.startswith("//") else "", urllib.parse.quote(p))


def _meta(db, key):
    """A meta value, or None when it isn't set or the database has no meta table yet (a brand-new file). Any other
    error (an unreadable, damaged meta) is raised: such a database is never set up again over itself."""
    try:
        row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError as ex:
        if str(ex).lower().startswith("no such table"):
            return None
        raise
    return row[0] if row else None


def _set_meta(db, key, value):
    db.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (key, value))


def _is_busy(ex):
    """True when an SQLite error means another connection holds the lock (SQLITE_BUSY / SQLITE_LOCKED)."""
    name = getattr(ex, "sqlite_errorname", "") or ""
    text = str(ex).lower()
    return name.startswith(("SQLITE_BUSY", "SQLITE_LOCKED")) or "database is locked" in text or "busy" in text


def _busy_retry(action):
    """Decorator for the actions: when the database stays locked past BUSY_TIMEOUT, try once more after
    BUSY_RETRY_DELAY; still locked, a KnowledgeError the AI can pass on (BUSY_MESSAGE) instead of SQLite's own."""
    @functools.wraps(action)
    def run(*args, **kwargs):
        try:
            return action(*args, **kwargs)
        except sqlite3.OperationalError as ex:
            if not _is_busy(ex):
                raise
        time.sleep(BUSY_RETRY_DELAY)
        try:
            return action(*args, **kwargs)
        except sqlite3.OperationalError as ex:
            if not _is_busy(ex):
                raise
        raise KnowledgeError(BUSY_MESSAGE)
    return run


@contextlib.contextmanager
def _write(db):
    """One short write transaction (BEGIN IMMEDIATE ... COMMIT, rolled back on any error). Refused on a database a
    newer suite tool wrote. The first write of the day to a database no analyzer looks after is preceded by a
    backup (_backup_daily)."""
    if db.too_new:
        raise KnowledgeError("This project database was written by a newer version of a suite tool (schema %s; TBC MCP "
                             "knows %d), so TBC MCP only reads it. Ask the user to update TBC MCP." % (db.too_new, SCHEMA_VERSION))
    if not db.writable:
        raise KnowledgeError("Internal error: the project database was opened read only for this action.")
    _backup_daily(db)
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")


# ---------------------------------------------------------------------------
# a damaged database: never read on, written or set up again; restored from a backup (contract: Opening)
# ---------------------------------------------------------------------------
def backups_dir(path):
    """<shared>\\projects\\<slug>.backups, where Project Analyzer (and TBC, _backup_daily) keep copies of <slug>.db."""
    return os.path.splitext(path)[0] + ".backups"


def backups(path):
    """The copies of a database in its backups folder, oldest first (Project Analyzer's '<slug> <time>.db' names sort
    by time); [] when there are none."""
    d, stem = backups_dir(path), os.path.splitext(os.path.basename(path))[0]
    try:
        names = os.listdir(d)
    except OSError:
        return []
    return [os.path.join(d, n) for n in sorted(names) if fnmatch.fnmatch(n, stem + " *.db")]


def quick_check(path):
    """'ok', or what PRAGMA quick_check (or opening the file) found wrong with a database file; None when it couldn't
    be checked because another tool holds the lock."""
    try:
        db = sqlite3.connect(_uri(path), uri=True, timeout=BUSY_TIMEOUT)
        try:
            rows = db.execute("PRAGMA quick_check").fetchall()
        finally:
            db.close()
    except sqlite3.Error as ex:
        return None if _is_busy(ex) else "can't be opened: %s" % ex
    found = "; ".join(str(r[0]) for r in rows[:5])
    return "ok" if found == "ok" else found


def _damaged(path, name, problem):
    """The KnowledgeError for a damaged database: what is wrong, and how to put a backup back."""
    copies = backups(path)
    restore = ("With Project Analyzer installed, the user can put a backup back with: python analyze.py restore "
               "--project \"%s\" (it lists the backups, checks them and keeps the damaged file)." % name)
    if copies:
        restore += (" Without it: close every tool using this job, keep the damaged file aside, then copy the newest "
                    "backup, %s, to %s." % (copies[-1], path))
    else:
        restore += " There is no backup in %s." % backups_dir(path)
    return KnowledgeError("The job's project database %s is damaged (%s), so TBC MCP neither reads nor changes it. Tell "
                          "the user. %s" % (path, problem, restore))


_damage = {}  # normalized database path -> ((size, mtime_ns) when it was found damaged, what quick_check said)
# SQLite errors that mean the file itself is bad (a backup copy that hits one: the source is checked)
_CORRUPT = re.compile(r"malformed|not a database|disk i/o|corrupt", re.I)


def _file_stamp(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def _remember_damage(path, problem):
    """Note that a database is damaged, with its size and modified time, so a later write to it is refused even
    when the write itself wouldn't touch the damaged pages."""
    _damage[os.path.normcase(os.path.abspath(path))] = (_file_stamp(path), problem)


def known_damage(path):
    """What was found wrong with this database file, while it is still the same file (size and modified time);
    None when it wasn't found damaged, or was replaced since (a backup put back), which forgets the record."""
    key = os.path.normcase(os.path.abspath(path))
    record = _damage.get(key)
    if not record:
        return None
    if record[0] != _file_stamp(path):
        del _damage[key]
        return None
    return record[1]


def _check_damage(path, name, error):
    """A KnowledgeError when an SQLite error came from a damaged database (quick_check isn't ok; remembered for later
    writes), else None (the error is something else, e.g. a column an older database doesn't have yet)."""
    if _is_busy(error):
        return None
    found = quick_check(path)
    if found is None or found == "ok":
        return None
    _remember_damage(path, found)
    return _damaged(path, name, found)


# ---------------------------------------------------------------------------
# TBC's own backup of a database it looks after alone (contract: Opening; Project Analyzer's backups.make naming)
# ---------------------------------------------------------------------------
_backed_up = {}  # database path -> the local date TBC last found or made today's copy


def _backup_daily(db):
    """Before the first write of a day to a database no analyzer run looks after (meta source_root empty): a copy
    with SQLite's backup API in <shared>\\projects\\<slug>.backups\\<slug> YYYY-MM-DD HHMMSS.db, checked with
    quick_check (thrown away when it isn't ok), the newest BACKUPS_KEPT of '<slug> *.db' kept. "Today already" = the
    newest copy's name has today's date. A copy that fails (disk full, no permission, busy) is simply not made and
    the write goes ahead; but a copy that fails its check, or hits a corruption error, means the source may be
    damaged (as Project Analyzer's backups.make treats it): the source is checked, and when it isn't ok the damage
    is remembered and the damaged KnowledgeError stops the write."""
    if db.memory or db.created or not db.path or _meta(db, "source_root"):
        return
    today = datetime.date.today().isoformat()
    if _backed_up.get(db.path) == today:
        return
    stem = os.path.splitext(os.path.basename(db.path))[0]
    copies = backups(db.path)
    if copies and os.path.basename(copies[-1])[len(stem) + 1:].startswith(today):
        _backed_up[db.path] = today
        return
    target = os.path.join(backups_dir(db.path), "%s %s.db" % (stem, datetime.datetime.now().strftime("%Y-%m-%d %H%M%S")))
    partial = os.path.join(backups_dir(db.path), ".%s.partial" % os.path.basename(target))
    suspect = False
    try:
        os.makedirs(backups_dir(db.path), exist_ok=True)
        dest = sqlite3.connect(partial)
        try:
            db.backup(dest)  # a consistent snapshot of everything committed
            dest.execute("PRAGMA journal_mode = DELETE")  # one self-contained file (the copy took the WAL setting)
        finally:
            dest.close()
        if quick_check(partial) == "ok":
            os.replace(partial, target)
            for old in backups(db.path)[:-BACKUPS_KEPT]:
                os.remove(old)
            _backed_up[db.path] = today
        else:
            suspect = True
    except sqlite3.Error as ex:
        suspect = not _is_busy(ex) and bool(_CORRUPT.search(str(ex)))  # otherwise no copy today; the write goes ahead
    except OSError:
        pass  # no copy today (disk full, no permission); the write goes ahead
    finally:
        for leftover in (partial, partial + "-wal", partial + "-shm", partial + "-journal"):
            if os.path.exists(leftover):
                try:
                    os.remove(leftover)
                except OSError:
                    pass
    if suspect:
        found = quick_check(db.path)
        if found is not None and found != "ok":
            _remember_damage(db.path, found)
            raise _damaged(db.path, stem, found)
        _backed_up[db.path] = today  # the source is fine: the copy just failed; try again tomorrow


# ---------------------------------------------------------------------------
# opening
# ---------------------------------------------------------------------------
_INDEX_LINES = []   # the schema's "CREATE INDEX IF NOT EXISTS" lines, read once
_indexed = set()    # databases this server run already gave them


def ensure_indexes(db):
    """Run the schema's "CREATE INDEX IF NOT EXISTS" lines on a database TBC can write (contract: Indexes; they only
    ever add an index), once per database and server run. A line on a table or column this database doesn't have
    yet is skipped; a busy database is left for the next write."""
    if db.path in _indexed:
        return
    if not _INDEX_LINES:
        with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
            _INDEX_LINES.extend(line.strip() for line in f if line.startswith("CREATE INDEX IF NOT EXISTS"))
    for line in _INDEX_LINES:
        try:
            db.execute(line)
        except sqlite3.OperationalError as ex:
            if _is_busy(ex):
                return
    _indexed.add(db.path)


def _create(db):
    """Set up a new database: WAL, project-db.sql, then schema_version, project_id and created."""
    db.execute("PRAGMA journal_mode = WAL")
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        db.executescript(f.read())
    db.created = True
    with _write(db):
        if _meta(db, "schema_version") is None:  # another tool may have created it meanwhile
            _set_meta(db, "schema_version", str(SCHEMA_VERSION))
            _set_meta(db, "project_id", secrets.token_hex(6))
            _set_meta(db, "created", _now())


def connect(path, name=None, create=False, write=False):
    """Open a job's database with the suite's settings (BUSY_TIMEOUT busy timeout, autocommit + explicit
    transactions). Rows come back as sqlite3.Row.

    write:  open read-write (link and the note-writing actions). Without it the file is opened read only (SQLite URI
            mode=ro): no schema, no journal switch, no JSON import, so a read never changes it.
    create: make the database when it doesn't exist (runs project-db.sql in WAL mode, then sets schema_version,
            project_id, created and project_name); implies write. Without it a missing file raises KnowledgeError.
    A writable open also switches an existing database to WAL when it isn't yet, adds the schema's indexes
    (ensure_indexes), sets project_name when missing and imports an old <slug>.json next to it once
    (import_json_notes). A damaged database (unreadable meta, quick_check not ok) raises KnowledgeError, and is
    never set up again over itself; once found damaged, every writable open of the same file (same size and
    modified time) is refused, even when the write wouldn't touch the damaged pages.
    """
    exists = os.path.isfile(path)
    if not exists and not create:
        raise KnowledgeError("No project database %s." % path)
    write = write or create
    problem = known_damage(path) if write and exists else None
    if problem:  # found damaged before and not replaced since: a write could make it worse
        raise _damaged(path, name or os.path.splitext(os.path.basename(path))[0], problem)
    if not exists:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    if write:
        db = sqlite3.connect(path, timeout=BUSY_TIMEOUT, isolation_level=None, factory=_Db)
    else:
        db = sqlite3.connect(_uri(path), uri=True, timeout=BUSY_TIMEOUT, isolation_level=None, factory=_Db)
    db.path, db.writable = path, write
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = %d" % int(BUSY_TIMEOUT * 1000))
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
        if tables and "meta" not in tables:
            raise KnowledgeError("%s isn't a suite project database (it has no meta table), so TBC MCP leaves it alone. "
                                 "Ask the user what it is." % path)
        version = _meta(db, "schema_version")
        try:
            newer = version is not None and int(version) > SCHEMA_VERSION
        except ValueError:
            newer = True
        if newer:
            db.too_new = version
            return db  # read as far as we understand it; never written
        if version is None:
            if not write:
                raise KnowledgeError("The project database %s isn't set up yet (another tool may be creating it right "
                                     "now). Try again in a moment; action=link sets it up." % path)
            _create(db)
        elif write:
            if str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal":
                db.execute("PRAGMA journal_mode = WAL")
            ensure_indexes(db)
        if write and name and not _meta(db, "project_name"):
            with _write(db):
                _set_meta(db, "project_name", one_line(name))
        legacy = path[:-len(".db")] + ".json"
        if write and os.path.exists(legacy):
            import_json_notes(db, legacy)
        return db
    except sqlite3.DatabaseError as ex:
        db.close()
        problem = _check_damage(path, name or os.path.splitext(os.path.basename(path))[0], ex)
        if problem:
            raise problem from None
        raise
    except BaseException:
        db.close()
        raise


def _from_json(job):
    """An old JSON-only job, read without writing anything: an in-memory database made from project-db.sql with the
    JSON file's notes imported (the file is left as it is; the first write moves it into <slug>.db)."""
    db = sqlite3.connect(":memory:", isolation_level=None, factory=_Db)
    db.row_factory = sqlite3.Row
    db.writable, db.memory = True, True
    _create(db)
    import_json_notes(db, job["json"], rename=False)
    if not _meta(db, "project_name"):
        with _write(db):
            _set_meta(db, "project_name", job["name"])
    db.writable = False  # the actions on it are reads
    return db


def next_id(db, table, prefix):
    """The next free '<prefix>-N' id in `table` (N = highest existing + 1, retired rows included). Call inside the
    write transaction that inserts it."""
    row = db.execute("SELECT MAX(CAST(SUBSTR(id, %d) AS INTEGER)) FROM %s WHERE id GLOB '%s-[0-9]*'"
                     % (len(prefix) + 2, table, prefix)).fetchone()
    return "%s-%d" % (prefix, (row[0] or 0) + 1)


def import_json_notes(db, json_path, rename=True):
    """Import an old <slug>.json notes file into the database once, then rename it to *.json.imported (contract:
    Moving from the JSON notes files; same behaviour as project-analyzer's projectdb.import_json_notes).

    In one transaction: project_name from "name" (if not set); each folder into `folders` (tool civil3d); each note
    as a new fact with tool = its "source" (missing = civil3d), added/updated kept, sources
    [{"file": "user", "path": "project note"}] and origin {"note_id": "note-N"}. A file that doesn't parse is left
    alone. meta.json_notes_imported stops a second import when the rename fails (file in use); the rename is retried
    on the next writable open. rename=False leaves the file as it is (a read builds the notes in memory, _from_json).
    Returns the number of notes imported.
    """
    done = json_path + ".imported"
    if _meta(db, "json_notes_imported"):
        if rename:
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
    if rename:
        try:
            os.rename(json_path, done)
        except OSError:
            pass
    return count


# ---------------------------------------------------------------------------
# which job: every <slug>.db (and not yet imported <slug>.json), cached by file stamps (contract: Finding the job)
# ---------------------------------------------------------------------------
_index = {}  # file path -> (stamp, job dict or None)
_jobs = {"dir": None, "at": 0.0, "jobs": []}  # the last job_index of the configured folder, kept INDEX_TTL seconds


class _Busy(Exception):
    """A database another tool holds locked while the job index reads it (read again next time)."""


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
    """{name, slug, db, json, roots, folders} of one database, read without writing anything. A database that can't
    be read is listed with `damaged` (why) and no folders, so the user hears about it instead of the job vanishing;
    _Busy when another tool holds it locked."""
    stem = os.path.basename(path)[:-len(".db")]
    try:
        db = sqlite3.connect(_uri(path), uri=True, timeout=BUSY_TIMEOUT)
        try:
            db.execute("PRAGMA busy_timeout = %d" % int(BUSY_TIMEOUT * 1000))
            meta = dict(db.execute("SELECT key, value FROM meta WHERE key IN ('project_name', 'source_root', "
                                   "'job_folders')").fetchall())
            folders = [(r[0], r[1]) for r in db.execute("SELECT path, tool FROM folders").fetchall()]
        finally:
            db.close()
    except sqlite3.Error as ex:
        if _is_busy(ex):
            raise _Busy()
        return {"name": stem, "slug": stem, "db": path, "json": None, "source_root": None, "folders": [], "roots": [],
                "damaged": "can't be read (%s): TBC MCP neither reads nor changes it; a backup can be put back (python "
                           "analyze.py restore --project \"%s\" with Project Analyzer, or the newest copy in %s)"
                           % (ex, stem, backups_dir(path))}
    extra = _loads(meta.get("job_folders"), [])
    roots = [f for f, _ in folders] + ([meta["source_root"]] if meta.get("source_root") else []) + [
        f["path"] for f in (extra if isinstance(extra, list) else []) if isinstance(f, dict) and f.get("path")]
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


def forget_jobs():
    """Look at <shared>\\projects again on the next job_index (after link / unlink, or when a job may be new)."""
    _jobs["at"] = 0.0


def job_index(shared=None):
    """Every job in <shared>\\projects: its databases, plus old <slug>.json files without a database yet. The list of
    the configured folder is kept INDEX_TTL seconds (forget_jobs drops it); each file is read again only when it
    changed. shared: another shared folder (the repo audit); default the configured one. Files are never changed; a
    database that can't be read is listed with `damaged`, a JSON file that doesn't parse is skipped."""
    d = os.path.join(shared, "projects") if shared else projects_dir()
    if not shared and _jobs["dir"] == d and time.time() - _jobs["at"] < INDEX_TTL:
        return list(_jobs["jobs"])
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
            try:
                cached = (stamp, reader(path))
                _index[path] = cached
            except _Busy:
                cached = cached or (stamp, None)  # the last reading of it, if any; read again next time
        if cached[1]:
            jobs.append(cached[1])
    if not shared:
        _jobs.update({"dir": d, "at": time.time(), "jobs": jobs})
    return list(jobs)


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
    (any case). None when there is none (the projects folder is looked at again before saying so)."""
    if not slug(name or ""):
        return None
    s = slug(name)
    for fresh in (False, True):
        if fresh:
            forget_jobs()
        jobs = job_index()
        job = (next((j for j in jobs if j["slug"] == s), None)
               or next((j for j in jobs if j["name"].strip().lower() == name.strip().lower()), None))
        if job:
            return job
    return None


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
def opened(job, write=False, create=False):
    """A connection to the job's database, closed afterwards. Read only unless `write` (link and the note-writing
    actions); create: make it when it's new (link). An old JSON-only job is read from an in-memory copy of its notes
    and moved into a new <slug>.db on the first write. An SQLite error from a damaged database becomes a
    KnowledgeError saying how to restore a backup."""
    if not write and job.get("json") and not os.path.isfile(job["db"]):
        db = _from_json(job)
    else:
        db = connect(job["db"], job["name"], create=create or (write and bool(job.get("json"))), write=write)
    try:
        yield db
    except sqlite3.DatabaseError as ex:
        problem = None if db.memory else _check_damage(job["db"], job["name"], ex)
        if problem:
            raise problem from None
        raise
    finally:
        db.close()
        if write:
            _index.pop(job["db"], None)
            if job.get("json"):
                _index.pop(job["json"], None)
            forget_jobs()


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


@_busy_retry
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
    with opened(job, write=True) as db:
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


@_busy_retry
def update_note(fact_id, note, name, active_path, topics=None, date=None, key=None, confidence=None):
    """action=update: change the text (and optionally topics, date, key, confidence) of one of TBC's own facts and
    stamp 'updated'."""
    text = _clean_fact(note)
    fields = _options({"topics": topics, "date": date, "key": key, "confidence": confidence})
    job = resolve(name, active_path)
    with opened(job, write=True) as db:
        with _write(db):
            _own_fact(db, job, fact_id)
            sets, args = ["fact = ?", "updated = ?"], [text, _now()]
            for k, v in fields.items():
                sets.append("%s = ?" % k)
                args.append(json.dumps(v, ensure_ascii=False) if k == "topics" else v)
            db.execute("UPDATE facts SET %s WHERE id = ?" % ", ".join(sets), args + [fact_id])
            fact = _fact(db.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone())
    return _with_hints({"success": True, "action": "updated", "project": job["name"], "fact": fact}, text)


@_busy_retry
def remove_note(fact_id, name, active_path):
    """action=remove: retire one of TBC's own facts (hidden, kept, its id never reused). Another tool's fact is
    refused; it is corrected by adding one with supersedes."""
    job = resolve(name, active_path)
    with opened(job, write=True) as db:
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
    out.extend({"path": f["path"], "by": "project-analyzer", "job_folder": f["name"]} for f in job_folders(db))
    out.extend({"path": r["path"], "by": r["tool"]} for r in db.execute("SELECT path, tool FROM folders ORDER BY added, path"))
    return out


@_busy_retry
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
    with opened(job, write=True, create=created) as db:
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


@_busy_retry
def unlink(name, folder):
    """action=unlink: drop a folder TBC linked itself (never another tool's). The job and its facts stay."""
    if not folder:
        raise KnowledgeError("folder is required")
    job = find_project(name) if name else None
    if not job:
        raise KnowledgeError("No project named %r." % name)
    with opened(job, write=True) as db:
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
    """The first column of a COUNT query; 0 when a table or column it names isn't in this database (a busy or
    damaged database still raises)."""
    try:
        return db.execute(sql, args).fetchone()[0]
    except sqlite3.OperationalError as ex:
        if _is_busy(ex):
            raise
        return 0


def _has_table(db, table):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone())


def _missing_files(db):
    """How many distinct referenced paths are missing from the job folder (refs with status missing); counted once
    per connection (overview and the copy hint both need it)."""
    if db.missing is None:
        db.missing = _count(db, "SELECT COUNT(DISTINCT LOWER(COALESCE(normalized, raw))) FROM refs WHERE status = 'missing'")
    return db.missing


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


def reference_only(db):
    """REFERENCE_ONLY with the date of the last Project Analyzer run (meta last_run_finished), if there was one."""
    when = None if db.memory else _meta(db, "last_run_finished")
    return REFERENCE_ONLY % ((when or "")[:10] or "the last time a tool wrote to it")


def in_shared(path):
    """True when path is inside the suite's shared folder (job databases, their backups and User Knowledge folders),
    which is never a source for editing or importing."""
    try:
        root = os.path.normcase(os.path.abspath(shared_root())).rstrip("\\/")
        full = os.path.normcase(os.path.abspath(path))
        return full == root or full.startswith(root + os.sep)
    except (OSError, ValueError):
        return False


def _base(job, db):
    out = {"project": _meta(db, "project_name") or job["name"], "database": job["db"],
           "reference_only": reference_only(db)}
    if db.memory:
        out["database"] = None
        out["old_notes_file"] = ("This job's notes are still in the old notes file %s; they move into %s the first time "
                                 "TBC writes to the job (link or add)." % (job["json"], job["db"]))
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


@_busy_retry
def list_notes(name, active_path, limit=100):
    """action=list: the named job, or the job the open .vce belongs to. When no job matches, the known jobs and a
    hint to link one."""
    if name:
        return describe(resolve(name, None), limit)
    job = project_for_path(active_path)
    if not job:
        return {"project": None, "open_project": os.path.basename(active_path) if active_path else None,
                "shared_knowledge_dir": shared_root(),
                "known_projects": [dict({"name": j["name"], "folders": [f for f, _ in j["folders"]],
                                         "source_root": j.get("source_root")},
                                        **({"damaged": j["damaged"]} if j.get("damaged") else {})) for j in job_index()],
                "hint": "No project is linked to this folder yet. If it's one of the known projects (e.g. analysed by "
                        "Project Analyzer or set up in Civil 3D), link this folder to it; otherwise ask the user for a "
                        "project name. Then action=link."}
    return describe(job, limit)


@_busy_retry
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
                 "RFI), action=file, action=timeline, action=latest (the newest version of a file), action=checks (every "
                 "problem to check) and action=changes (what changed lately).")
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


@_busy_retry
def search(query, name, active_path, limit=20):
    """action=search: the job's documents through the full-text index (best parts first, with a snippet around
    the first match), plus the current facts containing every word (LIKE on fact and topics). The parts and their
    files are read in one query each. Without the zstandard package the hits come without snippets, with a note."""
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
            if _is_busy(ex):
                raise
            raise KnowledgeError("Search failed (%s); try plain words." % ex)
        blocks, hits = _Blocks(db), []
        parts = blocks.parts(row[0] for row in rows)
        files = _files_by_id(db, {p["file_id"] for p in parts.values()}, "id, path, kind, doc_date")
        for (part_id,) in rows:
            p = parts.get(part_id)
            if not p:
                continue
            f = files.get(p["file_id"])
            hit = {"file": p["file_id"], "path": f["path"] if f else None, "part": p["label"]}
            try:
                hit["snippet"] = _snippet(blocks.text(p), words)
            except KnowledgeError as ex:
                hit["snippet"] = None
                r["text_error"] = str(ex)
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


def _files_by_id(db, ids, columns="id, path"):
    """{file id: files row} of several files in one query (the paths of an answer)."""
    ids = [i for i in ids if i]
    out = {}
    for start in range(0, len(ids), 500):  # well below SQLite's limit on query parameters
        chunk = ids[start:start + 500]
        out.update((f["id"], f) for f in db.execute("SELECT %s FROM files WHERE id IN (%s)" % (columns, ",".join(
            "?" * len(chunk))), chunk).fetchall())
    return out


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
    for folder in job_folders(db):
        if _key(rel).startswith(_key(folder["path"]) + "\\"):
            rel = "%s%s>\\%s" % (FOLDER_PREFIX, folder["name"], os.path.abspath(rel)[len(normalize_folder(folder["path"])) + 1:])
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


@_busy_retry
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
        full = on_disk(db, f["path"]) if f["depth"] == 0 else None
        if full:
            r["absolute"] = full
    return r


@_busy_retry
def entity(ref, name, active_path, limit=50):
    """action=entity: a person, organization, place, structure, station, sheet or document number from Project
    Analyzer's connections, by id, name or alias (any case): its files, events, stories and the facts whose topics
    name it. Found in SQL (the name index, then the aliases), its events filtered and ordered in SQL."""
    ref = one_line(ref)
    if not ref:
        raise KnowledgeError("name is required: e.g. 'John Smith', 'MH-3', 'C-104', 'RFI 12'.")
    job = resolve(name, active_path)
    with opened(job) as db:
        r = _base(job, db)
        e = _find_entity(db, ref)
        if not e:
            similar = db.execute("SELECT name, type, files FROM intel_entities WHERE name LIKE ? OR aliases LIKE ? "
                                 "ORDER BY files DESC LIMIT 15", ("%" + ref + "%", "%" + ref + "%")).fetchall()
            r["found"] = False
            r["similar"] = [{"name": c["name"], "type": c["type"], "files": c["files"]} for c in similar]
            r["facts"] = _facts(db, "(f.topics LIKE ? OR f.fact LIKE ?)", ("%" + ref + "%",) * 2, limit=limit)
            r["hint"] = "No entity with that exact name or alias. Try one of 'similar', or action=search."
            return r
        names = [e["name"]] + [str(a) for a in _loads(e["aliases"], []) if str(a).strip()]
        files = db.execute("SELECT f.id, f.path, f.doc_date, ef.count FROM intel_entity_files ef JOIN files f ON "
                           "f.id = ef.file_id WHERE ef.entity_id = ? ORDER BY ef.count DESC, f.path LIMIT ?",
                           (e["id"], int(limit))).fetchall()
        # its events: those of the files it appears in, and those whose title names it
        cond = " OR ".join(["e.file_id IN (SELECT file_id FROM intel_entity_files WHERE entity_id = ?)"]
                           + ["instr(lower(e.title), ?) > 0"] * len(names))
        events = db.execute("SELECT e.date, e.kind, e.title, g.path FROM intel_events e LEFT JOIN files g ON "
                            "g.id = e.file_id WHERE %s ORDER BY e.date LIMIT ?" % cond,
                            [e["id"]] + [n.lower() for n in names] + [int(limit)]).fetchall()
        scond = " OR ".join(["title LIKE ? OR subject LIKE ? OR refs LIKE ? OR people LIKE ?"] * len(names))
        found = db.execute("SELECT * FROM intel_stories WHERE %s ORDER BY first_date LIMIT 20" % scond,
                           [x for n in names for x in ("%" + n + "%",) * 4]).fetchall()
        steps = collections.defaultdict(list)
        if found:
            for st in db.execute("SELECT * FROM intel_story_steps WHERE story_id IN (%s) ORDER BY story_id, position"
                                 % ",".join("?" * len(found)), [s["id"] for s in found]).fetchall():
                if len(steps[st["story_id"]]) < 30:
                    steps[st["story_id"]].append({"date": st["date"], "kind": st["kind"], "who": st["who"], "what": st["what"]})
        stories = [{"id": s["id"], "title": s["title"], "first_date": s["first_date"], "last_date": s["last_date"],
                    "people": _loads(s["people"], []), "amounts": _loads(s["amounts"], []), "steps": steps.get(s["id"], [])}
                   for s in found]
        fcond = " OR ".join(["f.topics LIKE ?"] * len(names))
        r.update({"found": True, "entity": {"name": e["name"], "type": e["type"], "aliases": _loads(e["aliases"], []),
                                            "files": e["files"], "mentions": e["mentions"], "first_date": e["first_date"],
                                            "last_date": e["last_date"], "related": _loads(e["related"], [])},
                  "files": [{"file": f["id"], "path": f["path"], "date": f["doc_date"], "mentions": f["count"]} for f in files],
                  "events": [{"date": x["date"], "kind": x["kind"], "title": x["title"], "path": x["path"]} for x in events],
                  "stories": stories,
                  "facts": _facts(db, "(%s)" % fcond, ["%" + n + "%" for n in names], limit=limit)})
    return r


def _find_entity(db, ref):
    """The intel_entities row whose id, name or one alias is `ref` (any case); the one in most files when several
    are. None when none is."""
    low = ref.lower()
    rows = db.execute("SELECT * FROM intel_entities WHERE id = ?", (ref,)).fetchall()
    rows += db.execute("SELECT * FROM intel_entities WHERE name = ? COLLATE NOCASE", (ref,)).fetchall()
    # aliases are a JSON list: narrowed in SQL, then compared whole (any case)
    rows += [c for c in db.execute("SELECT * FROM intel_entities WHERE instr(lower(aliases), ?) > 0", (low,)).fetchall()
             if any(str(a).lower() == low for a in _loads(c["aliases"], []))]
    if not rows:
        return None
    return max(rows, key=lambda c: c["files"] or 0)


@_busy_retry
def timeline(name, active_path, date_from=None, date_to=None, limit=200):
    """action=timeline: Project Analyzer's events plus the dated current facts, in date order, optionally between
    two dates (YYYY, YYYY-MM or YYYY-MM-DD; both ends included: a 'YYYY-MM' end takes in that whole month). The
    events are filtered, ordered and cut to `limit` in SQL (the date index), and counted with COUNT(*)."""
    for d in (date_from, date_to):
        if d and not _DATE.match(str(d)):
            raise KnowledgeError("from and to must be YYYY, YYYY-MM or YYYY-MM-DD.")
    lo, hi = date_from or "", (date_to or "9999") + "￿"
    limit = int(limit)
    job = resolve(name, active_path)
    with opened(job) as db:
        r = _base(job, db)
        items = [{"date": e["date"], "kind": e["kind"], "title": e["title"], "path": e["path"], "from": "documents"}
                 for e in db.execute("SELECT e.date, e.kind, e.title, g.path FROM intel_events e LEFT JOIN files g ON "
                                     "g.id = e.file_id WHERE e.date >= ? AND e.date <= ? ORDER BY e.date, e.title LIMIT ?",
                                     (lo, hi, limit)).fetchall()]
        total = _count(db, "SELECT COUNT(*) FROM intel_events WHERE date >= ? AND date <= ?", (lo, hi))
        facts = [{"date": f["date"], "kind": "fact", "title": f["fact"], "fact": f["id"], "by": f["by"]}
                 for f in _facts(db, "f.date IS NOT NULL AND f.date >= ? AND f.date <= ?", (lo, hi))]
        items = sorted(items + facts, key=lambda x: (x["date"] or "", x["title"] or ""))
        r["events"] = items[:limit]
        if total + len(facts) > limit:
            r["more"] = "%d more: narrow it with from / to." % (total + len(facts) - limit)
    return r


# ---------------------------------------------------------------------------
# what changed, which checks, which version (contract: What to tell the AI)
# ---------------------------------------------------------------------------
_SEVERITY_ORDER = "CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'info' THEN 2 ELSE 3 END"
MAX_CHECK_FILES = 10  # action=checks: file paths shown per check


@_busy_retry
def checks(name, active_path, severity=None, kind=None, limit=50):
    """action=checks: Project Analyzer's problems to check (intel_checks), high first, then medium, info, then by
    kind and title; optionally one severity and/or one kind (any case). Each with its file paths (at most
    MAX_CHECK_FILES, resolved in one query), plus the counts of every check by severity and by kind."""
    job = resolve(name, active_path)
    where, args = ["1"], []
    if severity:
        where.append("severity = ? COLLATE NOCASE")
        args.append(str(severity).strip())
    if kind:
        where.append("kind = ? COLLATE NOCASE")
        args.append(str(kind).strip())
    where = " AND ".join(where)
    with opened(job) as db:
        r = _base(job, db)
        rows = db.execute("SELECT id, severity, kind, title, detail, refs, files FROM intel_checks WHERE %s ORDER BY %s, "
                          "kind, title, id LIMIT ?" % (where, _SEVERITY_ORDER), args + [int(limit)]).fetchall()
        total = _count(db, "SELECT COUNT(*) FROM intel_checks WHERE %s" % where, args)
        file_ids = {row["id"]: [str(i) for i in _loads(row["files"], []) if i] for row in rows}
        paths = _files_by_id(db, {i for ids in file_ids.values() for i in ids[:MAX_CHECK_FILES]})
        out = []
        for c in rows:
            ids = file_ids[c["id"]]
            item = {"id": c["id"], "severity": c["severity"], "kind": c["kind"], "title": c["title"], "detail": c["detail"],
                    "files": [paths[i]["path"] if i in paths else i for i in ids[:MAX_CHECK_FILES]]}
            refs = _loads(c["refs"], [])
            if refs:
                item["refs"] = refs
            if len(ids) > MAX_CHECK_FILES:
                item["more_files"] = len(ids) - MAX_CHECK_FILES
            out.append(item)
        r.update({"checks": out, "total": total,
                  "by_severity": {k or "": n for k, n in db.execute(
                      "SELECT severity, COUNT(*) FROM intel_checks GROUP BY severity ORDER BY %s" % _SEVERITY_ORDER)},
                  "by_kind": {k or "": n for k, n in db.execute(
                      "SELECT kind, COUNT(*) FROM intel_checks GROUP BY kind ORDER BY COUNT(*) DESC, kind")}})
        if severity:
            r["severity"] = severity
        if kind:
            r["kind"] = kind
        if total > len(out):
            r["more"] = "%d more: raise limit, or filter by severity / kind." % (total - len(out))
        if not _count(db, "SELECT COUNT(*) FROM intel_checks"):
            r["hint"] = ("No checks for this job. Project Analyzer finds them when it reads the job folder (missing "
                         "files, amounts or revisions that differ, questions without a reply); without it there are none.")
        else:
            r["hint"] = ("Problems Project Analyzer found in the job's files, to check - not facts. Tell the user before "
                         "relying on something a check is about; open a file with action=file.")
    return r


@_busy_retry
def changes(name, active_path, since=None, file=None, limit=50):
    """action=changes: what changed, newest first. requirement_changes: Project Analyzer's events of kind 'change'
    (a document or email saying "going forward", "no longer", "revised spec"), by the date of the document;
    file_changes: what its updates found changed in the job folder (the file_changes table, when the database has
    it), by when it was seen. Since a date (YYYY, YYYY-MM or YYYY-MM-DD; default the last 30 days unless a file is
    given) and/or for one file (id or path)."""
    if since and not _DATE.match(str(since)):
        raise KnowledgeError("since must be YYYY, YYYY-MM or YYYY-MM-DD.")
    if not since and not file:
        since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    job = resolve(name, active_path)
    limit = int(limit)
    with opened(job) as db:
        r = _base(job, db)
        f = _find_file(db, file) if file else None
        where, args = ["e.kind = 'change'"], []
        if since:
            where.append("e.date >= ?")
            args.append(since)
        if f:
            where.append("e.file_id = ?")
            args.append(f["id"])
        where = " AND ".join(where)
        events = db.execute("SELECT e.date, e.title, e.confidence, e.location, e.file_id, g.path FROM intel_events e "
                            "LEFT JOIN files g ON g.id = e.file_id WHERE %s ORDER BY e.date DESC, e.title LIMIT ?"
                            % where, args + [limit]).fetchall()
        r.update({"since": since, "requirement_changes": [
            {k: v for k, v in (("date", x["date"]), ("title", x["title"]), ("path", x["path"]), ("file", x["file_id"]),
                               ("where", x["location"]), ("confidence", x["confidence"])) if v} for x in events],
            "requirement_changes_total": _count(db, "SELECT COUNT(*) FROM intel_events e WHERE " + where, args)})
        if f:
            r["file"] = {"id": f["id"], "path": f["path"]}
        if _has_table(db, "file_changes"):
            where, args = ["1"], []
            if since:
                where.append("seen >= ?")
                args.append(since)
            if f:
                where.append("(file_id = ? OR path = ? COLLATE NOCASE)")
                args += [f["id"], f["path"]]
            where = " AND ".join(where)
            rows = db.execute("SELECT id, file_id, path, change, seen, mtime, old_path, summary, details FROM file_changes "
                              "WHERE %s ORDER BY seen DESC, id DESC LIMIT ?" % where, args + [limit]).fetchall()
            r["file_changes"] = [{k: v for k, v in (("seen", x["seen"]), ("change", x["change"]), ("path", x["path"]),
                                                    ("file", x["file_id"]), ("old_path", x["old_path"]),
                                                    ("modified", x["mtime"]), ("summary", x["summary"]),
                                                    ("details", _loads(x["details"], None))) if v} for x in rows]
            r["file_changes_total"] = _count(db, "SELECT COUNT(*) FROM file_changes WHERE " + where, args)
        if not r["requirement_changes"] and not r.get("file_changes"):
            r["hint"] = ("No changes found%s. Project Analyzer finds them in the job's documents and on each update of "
                         "the job folder; without it there are none. Widen it with since (e.g. since=2026-01)."
                         % (" since %s" % since if since else ""))
        else:
            r["hint"] = ("requirement_changes: the newest one about a thing is the one to follow, unless a fact says "
                         "otherwise - tell the user which you follow. file_changes: files Project Analyzer saw changed, "
                         "removed or moved in the job folder. Open one with action=file.")
    return r


# A file name's series key, as Project Analyzer's analyzer/series.py (and Civil 3D MCP's seriesKey) make it: dates,
# "rev N", "current", "copy" and the like taken out, so the versions of one drawing share it
_SERIES_REMOVE = re.compile(r"\b(?:\d{8}|\d{6}|\d{2}[-_ ]\d{2}[-_ ]\d{2,4}|current|copy|backup|bak|old|new|test|void|draft|"
                            r"final|rev(?:ision)?\s*\d*|v\d+|to)\b|\(\d+\)", re.I | re.A)


def series_key(file_name):
    """'C-101 rev2 (2).dwg' -> 'c 101': Project Analyzer's series key of a file name."""
    stem = ntpath.splitext(ntpath.basename((file_name or "").replace("/", "\\")))[0]
    key = re.sub(r"[\s_.-]+", " ", _SERIES_REMOVE.sub(" ", stem), flags=re.A).strip().lower()
    return key or stem.lower()


def _words(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split()


@_busy_retry
def latest(file_name, name, active_path, near=None):
    """action=latest: the newest version of a file, from Project Analyzer's version list (intel_series; contract:
    latest). The series a name or path points to: an exact path, a path ending in it, the series key of the name
    (`key = ? COLLATE NOCASE`), a key starting with it, then a path containing it; drawings first. Each series:
    its latest member (modified last), the older ones newest first (at most 10), `note` when a higher revision in
    the names is older, and `folders` when the name is in several folders. near: words about the folder ('phase 2
    area b'): only members whose path has all of them as whole words are kept. The same as Civil 3D MCP's
    projectLatest."""
    wanted = (file_name or "").strip().strip('"').replace("/", "\\")
    if not wanted:
        raise KnowledgeError("name is required: a file name or path, e.g. C-101 or Drawings\\C-101.dwg.")
    job = resolve(name, active_path)
    with opened(job) as db:
        r = _base(job, db)
        r["name"] = file_name
        if near:
            r["near"] = near
        if not _has_table(db, "intel_series") or not _count(db, "SELECT COUNT(*) FROM intel_series"):
            r.update({"series": [], "hint": "This job's database has no version list yet: Project Analyzer builds it when "
                      "it reads the job folder. Without it, ask the user which file is the latest, or look in the job "
                      "folder (action=search finds a file by its words)."})
            return r
        escaped = wanted.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        key = series_key(wanted.split("\\")[-1])
        ekey = key.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        ids = []
        for sql, value in (("path = ? COLLATE NOCASE", wanted), ("path LIKE ? ESCAPE '!'", "%\\" + escaped),
                           ("key = ? COLLATE NOCASE", key), ("key LIKE ? ESCAPE '!'", ekey + "%"),
                           ("path LIKE ? ESCAPE '!'", "%" + escaped + "%")):
            ids = [row[0] for row in db.execute("SELECT DISTINCT series_id FROM intel_series WHERE %s LIMIT 20" % sql,
                                                (value,)).fetchall()]
            if ids:
                break
        members = collections.OrderedDict((i, []) for i in ids)
        if ids:
            for m in db.execute("SELECT * FROM intel_series WHERE series_id IN (%s) ORDER BY series_id, position"
                                % ",".join("?" * len(ids)), ids).fetchall():
                members[m["series_id"]].append(m)
        found = [m for m in members.values() if m]
        hints = _words(near)
        if hints:
            found = [k for k in ([m for m in ms if set(hints) <= set(_words(m["path"]))] for ms in found) if k]
        found.sort(key=lambda ms: (ms[0]["kind"] != "cad", ms[0]["key"] or ""))
        def member(m):
            full = on_disk(db, m["path"])
            out = {"path": m["path"], "absolute": full, "exists": bool(full) and os.path.exists(_long(full)),
                   "modified": (m["modified"] or "")[:10] or None}
            if m["title_date"]:
                out["title_block_date"] = m["title_date"]
            if m["revision"]:
                out["revision"] = m["revision"]
            return out

        series = []
        for ms in found:
            last = ms[-1]
            item = {"key": last["key"], "kind": last["kind"], "versions": len(ms), "latest": member(last)}
            if last["note"] and not hints:
                item["note"] = last["note"]
            item["older"] = [member(m) for m in ms[:-1][::-1][:10]]
            folders = {ntpath.dirname(m["path"]).lower() for m in ms}
            if len(folders) > 1:
                item["folders"] = len(folders)
            series.append(item)
        r["series"] = series
        r["hint"] = ("No file by that name in the job's version list. Ask the user, or use action=search." if not series else
                     "A TBC project or file the user already has open comes first. The latest is the one modified last; "
                     "say which file you used and when it was modified. When one name is in several folders "
                     "(folders > 1) that look like different areas (phases, areas, sites) rather than dated deliveries "
                     "of one drawing, ask which, or pass near with the user's words about the folder.")
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


def _in_copy(db, relative):
    """(absolute path, exists) for a stored path (on_disk: in the job folder or one of the job's other folders);
    (None, False) when its folder isn't known."""
    if relative is None:
        return None, False
    full = on_disk(db, relative)
    if not full:
        return None, False
    full = os.path.normpath(full)
    return full, os.path.exists(full)


_STATUS_ORDER = {"found": 0, "found by name": 1, "ambiguous": 2, "missing": 3}


@_busy_retry
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
        # by the normalized path (its NOCASE index answers it), else as written (raw has no index: only on a miss)
        for column, value in (("normalized", written), ("raw", str(path))):
            rows = db.execute("SELECT r.*, g.path AS from_path FROM refs r LEFT JOIN files g ON g.id = r.file_id "
                              "WHERE r.%s = ? COLLATE NOCASE" % column, (value,)).fetchall()
            if rows:
                break
        if rows:
            best = sorted(rows, key=lambda x: _STATUS_ORDER.get((x["status"] or "").lower(), 9))[0]
            status = (best["status"] or "unknown").lower()
            r.update({"source": "refs", "status": status, "times_referenced": len(rows),
                      "referenced_by": sorted({x["from_path"] for x in rows if x["from_path"]})[:10]})
            if best["target_path"]:
                full, exists = _in_copy(db, best["target_path"])
                r.update({"relative": best["target_path"], "absolute": full, "exists": exists})
                if not root:
                    r["note"] = "The project database has no source_root, so only the relative path is known."
                elif not exists:
                    r["note"] = ("The job folder (%s) isn't reachable from this computer, or the file was moved since the "
                                 "analysis." % root)
            if status == "missing":
                if best["expected_path"]:
                    where, _ = _in_copy(db, best["expected_path"])
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
                full, exists = _in_copy(db, relative)
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
def _long(path, always=False):
    """The \\\\?\\ form of an absolute Windows path of LONG_PATH characters or more (always=True: of any absolute
    path), so files deep in a folder tree open past Windows' 260-character limit; other paths as they are."""
    if os.name != "nt" or not path or path.startswith("\\\\?\\") or not os.path.isabs(path) or (
            len(path) < LONG_PATH and not always):
        return path
    path = os.path.normpath(path)  # a \\?\ path is used exactly as written: no '..', no forward slashes
    return "\\\\?\\UNC\\" + path[2:] if path.startswith("\\\\") else "\\\\?\\" + path


def list_files(directory, limit=500, skip=None, problems=None):
    """Files under a folder: relative path, size and UTC modified time, sorted, at most `limit`. `skip`: a
    subfolder name (any case) left out at the top level. Long paths are read in their \\\\?\\ form; a file or folder
    that can't be read is left out and, when `problems` is a list, noted there ({path, error}). Returns
    (files, truncated)."""
    files, truncated = [], False
    root = _long(os.path.abspath(directory), always=True)
    if os.path.isdir(root):

        def failed(ex):
            if problems is not None:
                problems.append({"path": os.path.relpath(ex.filename, root) if ex.filename else directory,
                                 "error": ex.strerror or str(ex)})

        for dp, dns, fns in os.walk(root, onerror=failed):
            if skip and dp == root:
                dns[:] = [d for d in dns if d.lower() != skip.lower()]
            dns.sort()
            sub = dp[len(root):].lstrip("\\/")
            for fn in sorted(fns):
                if len(files) >= limit:
                    truncated = True
                    break
                rel = os.path.join(sub, fn) if sub else fn
                try:
                    st = os.stat(os.path.join(dp, fn))
                except OSError as ex:
                    if problems is not None:
                        problems.append({"path": rel, "error": ex.strerror or str(ex)})
                    continue
                files.append({"path": rel, "size": st.st_size,
                              "modified": datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc)
                              .isoformat(timespec="seconds").replace("+00:00", "Z")})
            if truncated:
                break
    files.sort(key=lambda f: f["path"].lower())
    return files, truncated


def _unreadable(problems):
    """The note for files list_files had to leave out (None when there were none)."""
    if not problems:
        return None
    return {"files": problems[:20], "hint": "These couldn't be read (in use, no permission, or a damaged name) and are "
                                            "left out. Tell the user if one of them matters."}


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
    with text), else None (also when the file can't be looked at)."""
    if not row or row["status"] not in ("done", "partial", "duplicate"):
        return None
    try:
        st = os.stat(_long(full))
    except OSError:
        return None
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
        with open(_long(full), "rb") as f:
            return b"\0" not in f.read(4096)
    except OSError:
        return False


def _direct_text(full, limit):
    """Text of a file TBC can read itself (at most `limit` characters are needed; more may be returned)."""
    if os.path.splitext(full)[1].lower() in office_text.EXTENSIONS:
        try:
            return office_text.read(_long(full))
        except office_text.OfficeTextError as ex:
            raise KnowledgeError("%s couldn't be read (%s)." % (os.path.basename(full), ex))
    with open(_long(full), "rb") as f:
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
    problems = []
    files, truncated = list_files(d, problems=problems)
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
    if problems:
        out["unreadable"] = _unreadable(problems)
    return out


@_busy_retry
def project_files(name, active_path):
    """action=files: the documents in the job's User Knowledge folder, each with whether Project Analyzer has read
    this version into the database and whether TBC can read it itself."""
    job = resolve(name, active_path)
    d = _ensure_files_dir(job)
    problems = []
    files, truncated = list_files(d, problems=problems)
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
    if problems:
        r["unreadable"] = _unreadable(problems)
    legacy = _legacy_files(job)
    if legacy:
        r["elsewhere"] = legacy
        r["elsewhere_hint"] = ("These files are directly in %s, outside User Knowledge, so they aren't read. Suggest the "
                               "user moves them into %s." % (os.path.dirname(d), d))
    return r


@_busy_retry
def read_file(rel, name, active_path, max_chars=MAX_READ_CHARS, offset=0):
    """action=read: one document of the job's User Knowledge folder (paths outside it are refused): the text Project
    Analyzer stored for this version of it, else read directly (text, .docx, .xlsx, .pptx). `offset` (characters)
    continues a long document where the last read stopped. Stored text that can't be decompressed here (no
    zstandard package) falls back to reading the file, or comes back empty with text_error."""
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
    if not os.path.isfile(_long(full)):
        raise KnowledgeError("No file %r in %s. Use action=files to list them (or action=file for the job's documents)."
                             % (rel, d))
    rel = os.path.relpath(full, d)
    max_chars, offset = int(max_chars), max(int(offset or 0), 0)
    text, problem = None, None
    with opened(job) as db:
        row = _fresh(_analyzer_docs(db).get(rel.lower()), full)
        if row:
            text_id = row["duplicate_of"] if row["status"] == "duplicate" and row["duplicate_of"] else row["id"]
            try:
                text, more = _Blocks(db).file_text(text_id, offset + max_chars)
                source = "the project database (read by Project Analyzer)"
            except KnowledgeError as ex:
                problem = str(ex)
    try:
        size = os.path.getsize(_long(full))
    except OSError as ex:
        raise KnowledgeError("%s can't be read (%s)." % (rel, ex.strerror or ex))
    if text is None:
        if not _readable_here(full):
            if problem:
                return {"project": job["name"], "file": rel, "size": size, "read_from": None, "text": "",
                        "text_error": problem}
            raise _cant_read(job, rel, full)
        try:
            text = _direct_text(full, offset + max_chars)
        except OSError as ex:
            raise KnowledgeError("%s can't be read (%s)." % (rel, ex.strerror or ex))
        # a plain file is read only as far as needed (4 bytes per character at most)
        more = len(text) > offset + max_chars or (os.path.splitext(full)[1].lower() not in office_text.EXTENSIONS
                                                   and size > (offset + max_chars) * 4 + 1)
        source = "the file"
    r = {"project": job["name"], "file": rel, "size": size, "read_from": source,
         "text": text[offset:offset + max_chars]}
    if problem:
        r["text_error"] = problem + " (Read from the file itself instead.)"
    if offset:
        r["offset"] = offset
    if more or len(text) > offset + max_chars:
        r["truncated"] = True
        r["next_offset"] = offset + max_chars
    return r


_texts = collections.OrderedDict()  # search: path -> ((size, mtime_ns), text) of User Knowledge documents read directly


def _cached_text(full):
    """The text of a User Knowledge document TBC reads itself, kept in memory by (path, size, modified time) so a
    search doesn't read every document again; the least recently used are dropped past TEXT_CACHE_CHARS."""
    st = os.stat(_long(full))
    stamp = (st.st_size, st.st_mtime_ns)
    hit = _texts.get(full)
    if hit and hit[0] == stamp:
        _texts.move_to_end(full)
        return hit[1]
    text = _direct_text(full, MAX_SCAN_BYTES)
    _texts[full] = (stamp, text)
    while len(_texts) > 1 and sum(len(t) for _, t in _texts.values()) > TEXT_CACHE_CHARS:
        _texts.popitem(last=False)
    return text


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
            text = _cached_text(full)
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
                 "reference_only": reference_only(db),
                 "hint": "The job's shared project database (also used by Civil 3D MCP and Project Analyzer). Follow "
                         "these facts and the user's own documents for the job (user_knowledge: guidelines, "
                         "requirements; tbc_project_notes action=read opens one); mention checks_high that bear on the task. More: tbc_project_notes "
                         "action=overview / search / entity / file / timeline / latest / checks / changes. Add what you "
                         "learn about this job with "
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
