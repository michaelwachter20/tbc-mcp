# Working on TBC MCP (guide for AI assistants and developers)

This file is for whoever changes this repository: an AI coding assistant or a person. It says how the code is laid
out, how to check a change, and the rules that keep it safe. For what the tool does for its users, read
[README.md](README.md); for how it works inside, read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What this is

An MCP server that lets an AI drive **Trimble Business Center (TBC) 2026.10** on the user's own PC:

```
AI client --stdio JSON-RPC--> mcp_server/tbc_mcp_server.py --TCP 127.0.0.1 + session token--> tbc_macro/TbcMcpBridge.py (inside TBC) --> TBC SDK
```

- `mcp_server/` runs in **CPython 3.12**: the standard library plus one package, `zstandard` (reads the project
  database's compressed text; `requirements.txt`). Add no other package.
- `tbc_macro/` and `mcp_server/ipy/` run **inside TBC** in **IronPython 3.4**: no f-strings, no CPython-only
  modules; .NET types through `clr`. `mcp_server/ipy/*.py` are sent to TBC on every call, so editing them needs no
  reinstall; `tbc_macro/TbcMcpBridge.py` is copied into TBC by `install_macro.ps1` and needs a reinstall and a TBC
  restart to change.

## Where things are

| Path | What |
|---|---|
| `mcp_server/tbc_mcp_server.py` | The MCP server: bridge client, safety layer, every tool handler (`t_*`), the `TOOLS` table, the server `INSTRUCTIONS` |
| `mcp_server/ipy/command_ui.py` | Panel engine, run inside TBC: reads and fills command panels, popups, panes and grids like a user |
| `mcp_server/ipy/{license,view,import_export}.py` | Inside-TBC helpers: license profile, Plan View info and screenshots, Import/Export panes |
| `mcp_server/knowledge.py` | TBC know-how: built-ins in `knowledge\` (committed, read only) merged with what is learned at runtime in `TBC_MCP_KNOWLEDGE_DIR` / `<shared>\tbc` (outside the repo); skills, scripts, lessons, panel layouts, preferences, the job-data guard, the shared folder (`shared_root`) |
| `mcp_server/projects.py` | The suite's project database, one SQLite file per job in `<shared>\projects\`, and each job's User Knowledge folder `<shared>\projects\<slug>\User Knowledge\` (`tbc_project_notes`) |
| `mcp_server/office_text.py` | Text of .docx, .xlsx and .pptx with the standard library only (user knowledge Project Analyzer hasn't read) |
| `mcp_server/practices.py` | The suite's good practices, `<shared>\practices.json` (`tbc_practices`) |
| `mcp_server/project-db.sql` | Copy of Project Analyzer's `schema/project-db.sql` (byte for byte; a test compares them) |
| `mcp_server/tbc_help.py` | Offline reader for TBC's installed HTML help |
| `tbc_macro/TbcMcpBridge.py` | The bridge macro inside TBC: socket server, info file, ribbon button with its status light, request handlers |
| `knowledge/` | The built-in know-how itself (data, not code); nothing writes here at runtime |
| `tests/` | Offline tests, live suites that drive a real TBC, and `dev/` probes |
| `tests/fixtures/` | Copies of Project Analyzer's `schema/fixture.db` and `fixture-practices.json` (a made-up job) |
| `tools/` | Release packaging, DLL reflection, SDK doc search |

## Checking a change

Offline (no TBC needed), run all five before committing:

```bash
py -3.12 tests\test_project_knowledge.py
```

```bash
py -3.12 tests\test_knowledge_split.py
```

```bash
py -3.12 tests\test_knowledge_audit.py
```

```bash
py -3.12 tests\test_server_fixes.py
```

```bash
py -3.12 tests\test_watchdog.py
```

With TBC open and the MCP Bridge switched on (green), the live suites exercise real commands on throwaway
objects and clean up after themselves, e.g. `py -3.12 tests\linework_tests.py`; results go to
`tests\<suite>_results.json` (git-ignored). Each file's docstring says what it needs, what it changes and how
to run it.

## Rules

1. **Version header.** Every code file starts with `# Written for and verified on Trimble Business Center 2026.10
   (build 44.0.9666.28609)...`. Keep it as line 1. For a newer TBC release, **add** handling and keep the 2026.10
   behavior.
2. **Add, never delete** knowledge: skills from another release get an appended `## TBC <release>` section, scripts
   are archived on overwrite, lessons from another release can't be removed.
3. **No job data in the repository** (suite contract). `knowledge\` holds general know-how only and is never
   written at runtime: everything learned goes to `knowledge.USER_ROOT` (outside the repo).
   `knowledge.check_general` refuses paths, job names, user-profile paths and `.vce`/`.job`/`.jxl` file names, and
   `tests\test_knowledge_audit.py` scans what's committed. Job facts go in the project database. `.gitignore`
   blocks job file types and `*.db`; never `git add -f` a job file. `tests\test_knowledge_split.py` proves a
   session of writes leaves the repository untouched.
4. **Shared knowledge follows the suite contract** in Project Analyzer's `docs/suite-knowledge.md` (table layout:
   `schema/project-db.sql`, copied to `mcp_server/project-db.sql`; update both copies and the fixtures together):
   WAL, 30 s busy timeout, short `BEGIN IMMEDIATE` writes; TBC writes only its own `facts` and `folders` rows
   (`tool = 'tbc'`), removes by setting `retired`, takes `fact-N` inside the write transaction, never writes a
   database with a newer `schema_version`; `practices.json`: only `source: "tbc"` entries, re-read before writing,
   keep unknown fields, atomic writes, never rewrite a file that doesn't parse. No tool keeps copies of job files.
5. **Be gentle with TBC.** Go through the existing safety helpers (`check_license`, `pace_command`, `wait_idle`,
   `safe_dismiss`, `check_known_danger`) instead of calling the bridge directly for anything that runs a command.
   Never press buttons on license popups, never cancel a progress window, delete through TBC's Delete command.
6. **Privacy.** License profiles stay in `%LOCALAPPDATA%\TBC-MCP`; screenshots capture TBC only; no tokens,
   license details or user-profile paths in anything shared.
7. **Standard library plus `zstandard`** on the server side (imported lazily, so the server still starts without
   it); IronPython 3.4 syntax inside TBC.
8. **Three kinds of knowledge**: how to drive TBC -> `knowledge.py` (`tbc_memory`, `tbc_skills`, `tbc_script`,
   `tbc_preferences`); facts about one job -> `projects.py` (`tbc_project_notes`); practice true on every job ->
   `practices.py` (`tbc_practices`). Keep the server `INSTRUCTIONS`, tool descriptions and
   `knowledge\skills\basics\working_safely_in_tbc.skill.md` saying the same.

## Adding a tool

1. Write a handler `def t_<name>(a):` in `tbc_mcp_server.py` (`a` is the arguments dict; return a dict or a string;
   raise `BridgeError` or `K.KnowledgeError` with a message that tells the AI what to do).
2. Add an entry to `TOOLS`: `(name, description, obj({...schema...}, [required]), handler, annotations)`. The
   description is what the AI reads: say when to use it and what it must not do.
3. Code that must run inside TBC goes in a new action of a module under `mcp_server/ipy/`, called with
   `run_ipy(module, action, args)`, or in a bridge handler if it's needed on every call.
4. Add an offline test when the logic doesn't need TBC, and mention the tool in the README's tool catalog.
