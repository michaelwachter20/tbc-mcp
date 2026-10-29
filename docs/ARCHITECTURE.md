# TBC MCP architecture

How TBC MCP works inside, for anyone (AI or human) reading or changing the code. What it does for its users is
in [README.md](../README.md); the rules for changing it are in [CLAUDE.md](../CLAUDE.md). Every code file also opens
with a docstring or comment block describing it in detail; this page ties them together.

Everything here was written for and verified on **Trimble Business Center 2026.10 (build 44.0.9666.28609)**.

## 1. The pieces

```mermaid
flowchart LR
    A["AI client<br/>(Claude Code, Claude Desktop, any MCP client)"] -- "MCP: JSON-RPC lines<br/>on stdin / stdout" --> B["mcp_server/tbc_mcp_server.py<br/>CPython 3.12, stdlib + zstandard"]
    B -- "one TCP request per call<br/>127.0.0.1:47821+, session token" --> C["tbc_macro/TbcMcpBridge.py<br/>IronPython 3.4 inside TBC"]
    C -- "Dispatcher.Invoke on TBC's UI thread" --> D[("TBC SDK<br/>open project")]
    B -- "run_ipy: sends code" --> E["mcp_server/ipy/*.py<br/>panel engine, view, license, import/export"]
    E -. "executed by the bridge's execute_python" .-> C
    B --> K[("knowledge\\ (in the repo, read only)<br/>built-in skills, scripts, lessons, panel layouts, preferences")]
    B <--> U[("Documents\\Project Knowledge\\tbc<br/>know-how learned on this PC")]
    B <--> S[("Documents\\Project Knowledge\\projects\\*.db<br/>one SQLite database per job, shared with<br/>Civil 3D MCP and Project Analyzer")]
    B <--> G[("...\\practices.json<br/>good practices of the suite")]
    B <--> L[("%LOCALAPPDATA%\\TBC-MCP\\license<br/>this user's license profile")]
    B --> H[("TBC's installed HTML help,<br/>Macros SDK XML docs")]
```

| Piece | Runs in | Role |
|---|---|---|
| **MCP server** (`mcp_server/tbc_mcp_server.py`) | CPython 3.12, a process the AI client starts | Speaks MCP over stdio, holds the 39 tools, the safety layer and the AI's instructions; talks to the bridge |
| **Bridge macro** (`tbc_macro/TbcMcpBridge.py`) | IronPython 3.4 inside TBC | A TBC macro: the ribbon button (Macros > MCP > MCP Bridge) starts a token-protected socket server on 127.0.0.1 and runs requests on TBC's UI thread |
| **Inside-TBC modules** (`mcp_server/ipy/*.py`) | IronPython 3.4 inside TBC, sent per call | Larger pieces of TBC-side logic: the panel engine (`command_ui.py`), Plan View (`view.py`), license profile (`license.py`), Import/Export panes (`import_export.py`) |
| **TBC know-how** (`mcp_server/knowledge.py`, `knowledge/` + the learned folder) | CPython | How to drive TBC: skills, saved scripts, lessons, recorded panel layouts, the user's preferences. Built-ins committed with the repo (read only); what is learned goes to `<shared>\tbc` |
| **Project database** (`mcp_server/projects.py`, `project-db.sql`) | CPython | Everything about one job: one SQLite database per job, filled by Project Analyzer, read and added to by Civil 3D MCP and TBC MCP |
| **Good practices** (`mcp_server/practices.py`) | CPython | Engineering practice true on every job, `<shared>\practices.json`, shared by the suite |
| **Help reader** (`mcp_server/tbc_help.py`) | CPython | Offline search and reading of TBC's installed HTML help |

## 2. Repository map

| Path | What it is |
|---|---|
| `mcp_server/tbc_mcp_server.py` | The server. Sections in file order: config from env vars; bridge client (`bridge_endpoint`, `call_bridge`, `run_ipy`); safety layer and command-panel tools; knowledge and object tools; help; Import/Export; license profile and TBC release detection; shared project knowledge; SDK doc search; the `TOOLS` table and `INSTRUCTIONS`; JSON-RPC loop (`handle`, `main`, `watch_tbc`) |
| `mcp_server/ipy/command_ui.py` | Panel engine: reads and fills TBC command panels, popups and docked panes (WinForms and WPF), clicks buttons, reads and edits grids |
| `mcp_server/ipy/view.py` | Active Plan View: visible extents, screen rectangle, screenshot, zoom |
| `mcp_server/ipy/license.py` | License fingerprint and profile (features, dates, which commands are licensed) |
| `mcp_server/ipy/import_export.py` | Drives TBC's Import (WPF) and Export (WinForms) panes; never presses Import or Export itself |
| `mcp_server/knowledge.py` | TBC know-how in two layers (built-in, learned), the shared folder (`shared_root`) and the job-data guard (`check_general`) |
| `mcp_server/projects.py` | The project database: finding the job, read actions (overview, search, file, entity, timeline, locate), TBC's facts and folders, JSON notes import, privacy checks |
| `mcp_server/practices.py` | `practices.json`: list, search, add, update, remove (TBC's own entries only) |
| `mcp_server/project-db.sql` | Copy of Project Analyzer's `schema/project-db.sql`, run when TBC creates a job's database |
| `mcp_server/tbc_help.py` | TBC help reader |
| `tbc_macro/TbcMcpBridge.py` | The bridge macro |
| `install_macro.ps1` | Copies the macro into `C:\ProgramData\Trimble\MacroCommands3\MCP` (asks for admin; `-Uninstall` removes it) |
| `knowledge/` | The built-in know-how (data, read only at runtime): `skills/`, `scripts/`, `memory/lessons.jsonl`, `commands/*.json`, `preferences.json` |
| `requirements.txt` | The one package the server needs besides the standard library: `zstandard` |
| `tests/` | Offline tests (`test_project_knowledge.py`, `test_knowledge_split.py`, `test_knowledge_audit.py`, `test_server_fixes.py`, `test_watchdog.py`), live suites per ribbon tab, the tab surveyor, smoke tests, shared helpers (`tbc_testkit.py`) |
| `tests/fixtures/` | Copies of Project Analyzer's `schema/fixture.db` and `fixture-practices.json`: a made-up job for the offline tests |
| `tests/tab_data/` | Survey results per ribbon tab, used to write the tab overview skills |
| `tests/dev/` | One-off development probes, and `run_ipy.ps1` to run TBC's IronPython outside TBC |
| `tools/` | `make_release.ps1` (local release zip), `reflect.ps1` (type members from TBC's DLLs), `sdkdoc.py` (SDK doc search) |
| `.github/workflows/release.yml` | Builds and publishes the release when a `v*` tag is pushed |
| `release_files.txt` | What goes into the release zip |

## 3. Life of a tool call

Using `command_ui_fill` as the example:

1. The AI client writes one JSON-RPC line on the server's stdin. `main()` parses it and queues it for the single
   tool-call worker thread, which handles requests one at a time, in order, so TBC never gets two at once. (Pings
   and notifications are answered by the reader thread at once, so the client hears back even while a tool call
   waits for TBC.)
2. `handle()` looks the tool up in `TOOL_MAP` and calls its handler, here `t_command_ui_fill(args)`.
3. The handler applies the safety layer: `wait_idle()` (TBC must not be computing), then `guard_fill()` (field
   order rules).
4. It calls `run_ipy("command_ui", "fill", args)`. `run_ipy` reads `mcp_server/ipy/command_ui.py`, puts
   `ACTION = "fill"` and `ARGS = {...}` in front of it, and sends the whole text with `call_bridge("execute_python")`.
5. `call_bridge` finds the bridge through the info file (`bridge_endpoint`): port, token and TBC's process id. A dead
   process id means TBC crashed, so the stale file is removed and the call fails with a clear message. Otherwise it
   opens a TCP connection to 127.0.0.1, sends `{id, token, method, params}` as one line and reads one line back.
6. The bridge checks the token, then runs `h_execute_python` on TBC's UI thread through `Dispatcher.Invoke` at
   Background priority, so TBC's own work comes first. The code's `result` variable and its printed output go back
   as `{id, ok: true, result}`, or `{id, ok: false, error, traceback}`.
7. Back in the server: a short settle pause (`FILL_SETTLE_S`, 0.8 s), then, when a button was pressed, `ui_after()`
   reports what happened (popups, field messages, the open command).
8. `handle()` wraps the result as an MCP text block (plus an image block when the result carries `_image_path`, as
   screenshots do). `BridgeError` and `KnowledgeError` become tool errors (`isError: true`) whose message tells
   the AI what to do; they don't become JSON-RPC errors.

Simple tools skip step 4: `list_points`, `create_layer` and the like call a bridge handler directly
(`call_bridge("list_points", args)`).

## 4. The bridge (inside TBC)

- **Starting and stopping.** `install_macro.ps1` installs the macro; TBC shows it as Macros > MCP > MCP Bridge. Each
  click toggles the bridge. The button's image is a green (running) or red (stopped) dot drawn in code; a 2 s
  WinForms timer keeps it matched to whether the socket is really listening. The light is reset to red when TBC's
  main window starts closing, before TBC saves its ribbon layout.
- **Discovery.** On start the bridge picks the first free port from 47821 (trying the next 9), makes a fresh token
  (a GUID) and writes `%TEMP%\tbc_mcp_bridge.json` with `{port, token, pid, version, started}`. The file is removed
  on stop and on a normal TBC exit. Its log is `%TEMP%\tbc_mcp_bridge.log`.
- **Protocol.** One JSON object per line, UTF-8. Only methods with an `h_<name>` handler can be called, and only
  with the right token.
- **Threading.** An accept thread plus one thread per connection read requests; each request is run on TBC's UI
  thread with `Dispatcher.Invoke` (synchronous: the connection thread waits). `run_command` is the exception: it is
  queued with `BeginInvoke` and answered at once with `{queued: true}`, because a command can open a modal panel.
- **Handlers.** `ping`, `project_info`, `list_entities`, `get_entity`, `list_points`, `list_layers`,
  `list_surfaces`, `surface_elevation`, `get_selection`, `set_selection`, `list_commands`, `run_command`,
  `create_points`, `create_linestring`, `create_layer`, `set_properties`, `delete_entities` (refuses: raw removal
  from containers crashed TBC; the MCP tool deletes with TBC's Delete command), `save_project`, `execute_python`.
  Writing handlers run as one undo step
  (`transact()`); `execute_python` does too when `transaction=true`, and rolls back on an exception.
- **Units.** TBC stores coordinates in meters; handlers convert to the project's display units unless asked for
  meters.

## 5. Inside-TBC modules (`run_ipy`)

Code under `mcp_server/ipy/` is read from disk and sent on every call, so changing it needs no macro reinstall and
no TBC restart. Each module ends with a dispatch on `ACTION` and sets `result`.

- **Panel engine** (`command_ui.py`). Actions: `state` (popups, open command, panes, and the fields, buttons, tabs,
  texts and grids of one scope: `command`, `dialog:<i>` or `pane:<title>`), `fill`, `click`, `close`, `license`,
  `close_dialog`, `forms` / `close_forms`, `editor_button`, `grid_read` / `grid_set`, `grid_cell_point` /
  `grid_click`. A fill finds each field by id, exact label, then unique label prefix; enters values the way a user
  does (focus, set or type, tab out so TBC validates); re-reads the panel after choices that change it; and queues
  the button press with `BeginInvoke` so a popup can't block the bridge. The module docstring lists the quirks it
  handles (checkboxes, coordinate boxes, numeric boxes, object pickers, WPF Enter handling, Infragistics grids).
- **View** (`view.py`): `info`, `screen_rect`, `screenshot`, `set_extents`.
- **License** (`license.py`): `fingerprint` (first 16 hex characters of a SHA-256 over the key id and licensed
  features; the raw key never leaves TBC) and `profile`.
- **Import/Export** (`import_export.py`): reads and sets the panes' state; the server presses the buttons.

## 6. The safety layer

All in `tbc_mcp_server.py` unless noted. New code that runs commands should go through these helpers.

| Guardrail | Where |
|---|---|
| License check before launching a command, without TBC's license popup | `check_license`, `command_ui.py` action `license` |
| License popups only ever closed with X | `is_license_dialog`, `safe_dismiss`, `t_tbc_dialogs` (`force` needed otherwise) |
| At least 2.5 s between command launches | `pace_command` (`TBC_MCP_COMMAND_GAP`) |
| A panel must stop changing before it is filled | `t_command_ui_open` (field list stable for 1.2 s) |
| Nothing happens while TBC computes; progress windows are never touched | `tbc_busy`, `wait_idle` (up to `TBC_MCP_IDLE_TIMEOUT`, 900 s) |
| Popups backed out of safely: only Cancel/Close/No/Abort, else close with X; one pass | `safe_dismiss` |
| TBC error reports logged and work stopped | `is_error_dialog`, `log_tbc_error` (`memory/tbc_errors.log` in the learned folder, outside the repo) |
| Commands known to act at once, or open a browser, need `confirm=true` | `check_known_danger` (lessons containing `DANGER_WORDS`) |
| Field-order rules | `guard_fill`, `FILL_ORDER_GUARDS` |
| Deletion through TBC's Delete command; import records refused | `t_delete_entities` |
| Imports need `confirm=true` | `t_import` |
| Screenshots of TBC only | `view_covered_by_other_app` (5x5 sample of the view) |
| Private data never shared | `projects.add_private` (bridge token, license fingerprint), `projects.check_private_text` (facts, practices, know-how) |
| Server exits when TBC dies | `watch_tbc` |

## 7. TBC know-how (`knowledge.py`, `knowledge/`, the learned folder)

The suite keeps three kinds of knowledge apart (Project Analyzer's `docs/suite-knowledge.md`): how to drive one
program (here), facts about one job (section 8) and good practices for every job (`practices.py`, section 8).

Two layers with the same layout:

- **Built-in**: `knowledge/` in the repository (`K.BUILTIN_ROOT`), shipped in the release zip. Never written at runtime.
- **Learned**: `TBC_MCP_KNOWLEDGE_DIR`, else `<shared>\tbc` (`K.USER_ROOT`). Every writer writes here, so nothing
  learned on a PC reaches the repository. Nothing renames or moves the shared folder (`shared_dir()`).

| File | Holds | Tool |
|---|---|---|
| `preferences.json` | The user's standing rules, appended to the server's instructions (`prefs_text`) | `tbc_preferences` |
| `skills/<category>/<name>.skill.md` | Verified procedures: frontmatter (`name`, `category`, `description`, `tbc_versions` ...) and markdown | `tbc_skills` |
| `scripts/<name>.py` | Saved IronPython scripts with a JSON `tbc-script` header; old versions in `scripts/_archive/` (learned folder) | `tbc_script` |
| `memory/lessons.jsonl` | One lesson per line `{id, ts, topic, tags, text, tbc_version}` | `tbc_memory` |
| `commands/<key>.json` | Recorded panel layouts and notes per command; options of project-data dropdowns are never recorded | automatic, `tbc_memory command=` |
| `memory/tbc_errors.log`, `memory/crash_log.md` | TBC error popups, crash notes (learned folder only) | - |

Reads merge both layers and the learned version wins: a skill or script of the same name, a command record of the
same key, a lesson or preference of the same id. Learned lessons and preferences are numbered from
`USER_ID_BASE + 1` (100001), so they never collide with built-in ids; changing a built-in preference stores a
learned copy with the same id, and removing a built-in lesson or preference stores `{"id", "retired"}` in the
learned file. Saving over a built-in skill or script (`overwrite=true`) or appending a version section writes a
learned copy (the built-in script's text is archived as version 1 there). A built-in script can't be retired.

Rules: add, never delete; one release's knowledge is never overwritten by another's (`append_version_section`,
script versions, lessons stamped with `tbc_version`); duplicates are not stored; writes are atomic. Lessons whose
topic is a command key surface when that command opens (`remembered_for_command`) and when code names it
(`lessons_relevant_to`).

**No job data in know-how.** Every writer calls `check_general`, which refuses absolute paths outside the program
and system folders, network paths, user-profile paths and private values, the names of jobs in the shared projects
folder (from each database's `project_name`, `source_root` and `folders`, and old JSON notes files), and
`.vce`/`.job`/`.jxl` file names. `tests/test_knowledge_audit.py` applies the same rules to everything committed
under `knowledge/`, and `.gitignore` blocks job file types and `*.db`. `tests/test_knowledge_split.py` runs every
writer in a session and checks the repository is unchanged.

## 8. The project database (`projects.py`) and good practices (`practices.py`)

The suite's contract is Project Analyzer's `docs/suite-knowledge.md`; the table layout is its
`schema/project-db.sql`, copied byte for byte to `mcp_server/project-db.sql` (`tests/test_project_knowledge.py`
checks it and the fixtures against their recorded SHA-256, and against the analyzer's files when its repository is
on the PC). In short:

- **Where.** `<shared>` = `PROJECT_KNOWLEDGE_DIR`, else `Documents\Project Knowledge`, or an earlier folder used as it is (`Documents\Civil3DMcp-KnowledgeBase`); nothing renames or moves it. `projects\<slug>.db` is
  one SQLite database per job; `projects\<slug>\` holds files the user puts there for the job; `practices.json` the
  good practices. No tool keeps copies of a job's files.
- **Connections.** One per action (`opened`). Reads open the file read only (SQLite URI `mode=ro`): no schema, no
  journal switch, no JSON import. `link` and the note actions open it read-write: an existing database is switched
  to WAL if it isn't yet and gets the schema's `CREATE INDEX IF NOT EXISTS` lines (`ensure_indexes`). Autocommit with
  explicit `BEGIN IMMEDIATE ... COMMIT` for each write (`_write`), so TBC can add a fact while a long Project
  Analyzer run writes; a 10 s busy timeout (`BUSY_TIMEOUT`), then one retry (`_busy_retry`), then a KnowledgeError
  saying the database is busy. A database whose `meta.schema_version` is newer than 1 is read, never written. A
  damaged one (an unreadable `meta`, or `PRAGMA quick_check` not ok after an SQLite error) is neither read nor
  set up again: the error names `analyze.py restore` and the newest file in `projects\<slug>.backups\`.
- **Backups.** Before the first write of a day to a database whose `meta.source_root` is empty (no analyzer looks
  after it), `_backup_daily` copies it with SQLite's backup API to `projects\<slug>.backups\<slug> YYYY-MM-DD
  HHMMSS.db` (Project Analyzer's naming), checks it with `quick_check` and keeps the newest 3.
- **Finding the job.** `job_index` reads `meta.project_name`, `meta.source_root` and the `folders` rows of every
  `projects\*.db` (read-only connections), cached per file by size and modified time of the database and its WAL
  file, the whole list kept 60 s (`INDEX_TTL`; a write or a name not found looks again); old `<slug>.json` notes
  files without a database count too, and a database that can't be read is listed with `damaged`. The open `.vce` belongs to the job whose folder
  contains it, compared case-insensitively on normalized absolute paths; the deepest folder wins.
- **Creating and importing.** `link` creates a new job's database (runs `project-db.sql`, sets `schema_version`,
  `project_id` (12 random hex), `created`, `project_name`). The first writable open while `<slug>.json` exists
  imports it once (until then a read builds the notes in memory, `_from_json`) (`import_json_notes`, the same as the analyzer's): name, folders (`tool` civil3d), each note as a fact owned
  by its `source` (none = civil3d) with its times, `sources` `[{"file": "user", "path": "project note"}]` and
  `origin` `{"note_id"}`; then the file is renamed `.json.imported` (`meta.json_notes_imported` stops a second import).
- **Reading.** `overview`, `search` (FTS5 `text_search` with `fts_query`: each word quoted, codes such as MH-3 or
  12+50 as phrases; snippets from the decompressed part; facts by `LIKE`), `file`, `entity`, `timeline`, `locate`,
  `latest` (`intel_series`), `checks` (`intel_checks`) and `changes` (events of kind `change`, `file_changes`), as
  the contract's "What to tell the AI" table says. Lookups are written `col = ? COLLATE NOCASE` so the schema's
  NOCASE indexes answer them, and filtering, ordering and limits happen in SQL. Text is decompressed in memory, block
  by block (`zstandard`, imported lazily; `zlib` and `none` codecs also read); without `zstandard`, search, read and
  file still answer, without the stored text. User Knowledge is read with `\\?\` paths when they are long; a file
  that can't be read is left out with a note. The first result of a session for a job
  carries a short overview (`notes_once`): key facts, TBC's own facts, `intel_checks` of severity high, the number
  of missing referenced files.
- **Writing.** Only TBC's own rows: facts with `tool = 'tbc'` (`add` checks for the same text among current facts
  and adds its source to TBC's own instead of a duplicate; `fact-N` is taken inside the write transaction; `update`;
  `remove` sets `retired`) and folders with `tool = 'tbc'` (`link`, `unlink`). Another tool's fact is corrected by
  adding one with `supersedes`. A fact's source is the open TBC project (`tbc:<path>`, the file name only when the
  project is inside the user profile) or the user.
- **Copied folders.** `locate` translates a path written in the job's files: `refs.normalized` (case-insensitive;
  its `target_path`, `status`, `expected_path`, `candidates`), then `meta.reference_roots` (original ->
  `source_root\in_copy\rest`). It never guesses.
- **Privacy and formats.** Facts and practices with private data are refused; facts in other reference formats are
  saved with hints.
- **Practices.** `practices.py` reads and writes `practices.json` by the contract's file rules: `practice-N` ids
  never reused, removing sets `retired`, duplicate check, only `source: "tbc"` entries changed, unknown fields kept,
  re-read before writing, atomic UTF-8 (no BOM, LF, 2-space indent) writes, a file that doesn't parse is never
  rewritten. `practices_text()` is appended to the server's instructions next to the preferences.

## 9. Configuration, files written, logs

Environment variables are listed in the README's Configuration table and at the top of `tbc_mcp_server.py`.
Files written outside the repo: the bridge info file and log in `%TEMP%`, license profiles in
`%LOCALAPPDATA%\TBC-MCP\license`, screenshots in `%TEMP%\tbc_mcp_view.png`, learned know-how (including
`memory/tbc_errors.log`) in `<shared>\tbc`, and project databases and `practices.json` in the shared folder.
Inside the repo: only the live suites' `tests/*_results.json` (git-ignored).
The server logs to stderr; stdout carries only MCP messages.

## 10. Tests and release

- **Offline:** `tests/test_project_knowledge.py` (project database on a copy of `tests/fixtures/fixture.db`,
  practices, the server over stdio), `tests/test_knowledge_split.py` (built-in and learned know-how, the job-data
  guard, nothing written into the repo), `tests/test_knowledge_audit.py`, `tests/test_server_fixes.py`,
  `tests/test_watchdog.py`. Run them before every commit.
- **Live** (TBC open, bridge green): `cad_edit_tests.py`, `survey_cogo_tests.py`, `linework_tests.py`,
  `drafting_tests.py`, `home_tests.py`, `selection_tests.py`, plus `test_mcp_stdio.py` and `test_v2_e2e.py`. They
  work on throwaway objects and clean up. `tab_survey.py` opens every tool on a ribbon tab without applying
  anything, and `write_tab_skill.py` turns its output into a tab overview skill.
- **Release:** pushing a `v*` tag runs `.github/workflows/release.yml`. It copies the paths in `release_files.txt`,
  strips caches, logs and license files, zips them and creates (or updates) the GitHub release.
  `tools/make_release.ps1` builds the same zip locally, taking the version from `SERVER_VERSION`.

## 11. Known issues

The documentation pass found a list of problems; they were then fixed and are covered by
`tests/test_server_fixes.py` where that is possible without TBC. Changes to code that runs inside TBC
(`tbc_macro/`, `mcp_server/ipy/`) are syntax-checked only until they are run against a live TBC.

Fixed:

- **Server:** a valid JSON message that isn't an object no longer crashes the server (`-32600`); pings are
  answered while a tool call waits for TBC (tool calls still run one at a time, in order, on a worker thread);
  `guard_fill` also refuses a required field that comes after the field needing it; `safe_dismiss` closes popups
  from the highest index down, so closing one can't shift the next; `ui_grid` re-reads a clicked row by its index,
  beyond row 500 too; `create_points` refuses numbers counted from `start_id` that already exist; `tbc_export` checks
  the path before opening the pane and doesn't call an untouched old file "exported"; `tbc_memory` with `command=`
  stores the lesson under the command, so the confirm gate and the panel reminder apply to it; `run_command` is
  marked destructive; dead code (`post_click`, `LAYER_TYPE_CODE`) removed.
- **Bridge (needs reinstalling the macro to take effect):** the raw `delete_entities` handler now refuses (deletion
  goes through TBC's Delete command only); `create_linestring` reports when `closed=true` couldn't be applied; a
  connection no longer handles a request after the bridge stopped; the exit hook is removed on stop.
- **Inside TBC (`mcp_server/ipy/`):** `license.py` no longer counts GetFeatures' error entry as a feature;
  `command_ui.py` restores hidden grid columns when a click is aborted, measures empty grids correctly, shows plain
  list boxes' on-screen text, refuses to un-select a WPF radio option (as for WinForms) and explains an empty button
  name.
- **Tests and tools:** `cad_edit_tests.py` deletes through TBC's Delete command; the live suites write results into
  `tests/` from any folder and accept `--keep` on its own; `test_v2_e2e.py` works on a copy of the knowledge base,
  places its point relative to the Plan View and sets an exit code; `drafting_tests.py` restores the Labeling Scale
  Factor and the block folder setting and deletes its test image; superseded, never-run tests removed;
  `write_tab_skill.py` works without a `tab` key (and `cad_tab_survey.py` writes one); `sdkdoc.py` honors
  `TBC_SDK_DOCS`, refreshes its cache and never caches an empty result; `reflect.ps1` lost a dead line;
  `tbc_help.py` lost its unused `html.parser` class.
- **Docs:** `TBC_MCP_INFO` was described as moving the bridge's info file. It only tells the server where to look
  (for tests with a stand-in bridge); the macro always writes to `%TEMP%`.

Still open (left as they are, with the reason):

- `import_export.py` relies on a non-public field named `a`, which may change between TBC releases: needs a live
  TBC to find a stable replacement.
- `command_ui.py` counts every visible WPF window as a popup, and some Infragistics paths (`_u_set`'s
  `UltraGridAction` lookup, `editor_button`, `UltraTabStrip` tabs) are unverified: changing them without a live TBC
  could break popup handling that works today.
- The bridge's `cmdData.Version` (0.1) differs from `BRIDGE_VERSION` (0.2.0): it is TBC's macro metadata, and
  changing it may affect how TBC registers the macro.
- Not bugs: `layer_serial` creates a layer for a name that doesn't exist (documented: "Layer name (created if
  missing)"), and `jsonable` always expands Python dicts and lists returned by your own `execute_python` code.
