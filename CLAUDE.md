# Working on TBC MCP (guide for AI assistants and developers)

This file is for whoever changes this repository: an AI coding assistant or a person. It says how the code is laid
out, how to check a change, and the rules that keep it safe. For what the tool does for its users, read
[README.md](README.md); for how it works inside, read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What this is

An MCP server that lets an AI drive **Trimble Business Center (TBC) 2026.10** on the user's own PC:

```
AI client --stdio JSON-RPC--> mcp_server/tbc_mcp_server.py --TCP 127.0.0.1 + session token--> tbc_macro/TbcMcpBridge.py (inside TBC) --> TBC SDK
```

- `mcp_server/` runs in **CPython 3.12**, standard library only (no pip installs, ever).
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
| `mcp_server/knowledge.py` | General TBC knowledge in `knowledge\` (committed): skills, scripts, lessons, panel layouts, preferences, the job-data guard |
| `mcp_server/projects.py` | Job knowledge shared with Civil 3D MCP and Project Analyzer, outside the repo (`tbc_project_notes`) |
| `mcp_server/tbc_help.py` | Offline reader for TBC's installed HTML help |
| `tbc_macro/TbcMcpBridge.py` | The bridge macro inside TBC: socket server, info file, ribbon button with its status light, request handlers |
| `knowledge/` | The general knowledge base itself (data, not code) |
| `tests/` | Offline tests, live suites that drive a real TBC, and `dev/` probes |
| `tools/` | Release packaging, DLL reflection, SDK doc search |

## Checking a change

Offline (no TBC needed), run all four before committing:

```bash
py -3.12 tests\test_project_knowledge.py
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
3. **No job data in the repository** (suite contract rule 8). `knowledge\` holds general know-how only;
   `knowledge.check_general` refuses paths, job names, user-profile paths and `.vce`/`.job`/`.jxl` file names, and
   `tests\test_knowledge_audit.py` scans what's committed. Job facts go in the shared project notes. `.gitignore`
   blocks job file types; never `git add -f` a job file.
4. **Shared project files follow the contract** in Project Analyzer's `docs/shared-project-knowledge.md`: same
   folder, slug and format as Civil 3D MCP; TBC changes only its own notes (`source: "tbc"`) and folders
   (`tbc_linked_folders`); re-read before writing; keep unknown fields; never rewrite a file that doesn't parse.
5. **Be gentle with TBC.** Go through the existing safety helpers (`check_license`, `pace_command`, `wait_idle`,
   `safe_dismiss`, `check_known_danger`) instead of calling the bridge directly for anything that runs a command.
   Never press buttons on license popups, never cancel a progress window, delete through TBC's Delete command.
6. **Privacy.** License profiles stay in `%LOCALAPPDATA%\TBC-MCP`; screenshots capture TBC only; no tokens,
   license details or user-profile paths in anything shared.
7. **Standard library only** on the server side; IronPython 3.4 syntax inside TBC.

## Adding a tool

1. Write a handler `def t_<name>(a):` in `tbc_mcp_server.py` (`a` is the arguments dict; return a dict or a string;
   raise `BridgeError` or `K.KnowledgeError` with a message that tells the AI what to do).
2. Add an entry to `TOOLS`: `(name, description, obj({...schema...}, [required]), handler, annotations)`. The
   description is what the AI reads: say when to use it and what it must not do.
3. Code that must run inside TBC goes in a new action of a module under `mcp_server/ipy/`, called with
   `run_ipy(module, action, args)`, or in a bridge handler if it's needed on every call.
4. Add an offline test when the logic doesn't need TBC, and mention the tool in the README's tool catalog.
