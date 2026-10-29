---
name: working_safely_in_tbc
tbc_versions: ["2026.10"]
category: basics
description: "READ FIRST. Every operating rule for driving Trimble Business Center through this MCP: the user's preferences, working rules, and what the tools do automatically."
requires_write: false
parameters: []
verified: "2026-10-13, compiled from live sessions with the user on TBC 2026.10"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

## Good habits (the built-in preferences; also see tbc_preferences and tbc_practices)

1. **Leave TBC tidy.** Close Layer Manager and every command panel, pane and view window you opened when you
   are done (run_command layermanager toggles Layer Manager; command_ui_close for panels). Clear selections you made.
2. **Point numbering and codes follow the job's practices** (`tbc_practices`). `create_points` numbers points
   without a `name` from the highest numeric ID + 1 and puts descriptions in the Feature code box.
3. **Pace commands.** TBC is slow to open commands but quick once a panel is open. Keep a panel open for repeated
   work; don't open commands back to back.
4. **Wait for TBC to finish computing** ("Compute Project / Computing the project"). Never act while it computes,
   and never press Cancel on a progress window.
5. **Online tools only when asked**: Send to RTX-PP, Processing Services and Internet Download (CORS/orbit data)
   go online or open a browser; run them only when the user asks.
6. **Don't record TBC crashes** as lessons or in skills. TBC sometimes crashes for no reason: tell the user, wait for
   them to restart it, and carry on.
7. When the user states a new lasting preference, record it with `tbc_preferences action=add`.
8. **The job database is for reference only.** Values for an edit or import come from the current source file
   the user names, never from `tbc_project_notes`; with none named, ask which file is current (see below).

## Before doing something

- Search the knowledge base: `tbc_skills action=search` (skills, scripts, lessons, remembered command panels).
- Check what is known about **this job**: `project_info` returns a short overview of its project database the first
  time (key facts, high checks, missing files); `tbc_project_notes action=overview` gives all of it. Follow its
  facts. Project Analyzer has usually read every document of the job into the database: `action=search` finds
  words and codes (MH-3, 12+50, C-104, RFI 12) in all of them, `action=entity` gives a person, structure, sheet or
  RFI with its files, events and story, `action=file` opens one document, `action=timeline` lists events by date.
- Follow the suite's **good practices** (listed in the server instructions; `tbc_practices action=search`).
- Job folders are usually **copies** of a project from another drive or server, so imported files and linked data
  still point at the original location. When TBC reports a missing or unresolved file, or a path doesn't exist,
  run `tbc_project_notes action=locate path=<path as TBC shows it>` before telling the user it's missing. If it
  says "not known", ask the user where the original folder was; never guess.
- **The job database is for reference only.** It is a snapshot of the job's files as of the last Project
  Analyzer run: use it to find and understand things (what a file says, where it is, who did what and when). Never
  use its coordinates, elevations, points, stations, dimensions, quantities or text as data to edit or import into
  the project. Take them from the current source file the user names; if they haven't named one, ask which file
  is current before changing anything.
- Read the command's help: `tbc_help action=read command=<key>`. It says what the command does and whether it
  **acts immediately** (no panel).
- Ask the user to save (or confirm it's a test copy) before experiments that change project-wide data
  (network adjustment, calibration, feature processing, coordinate system settings).

## What the tools enforce automatically

| Protection | Where |
|---|---|
| License check before opening; unlicensed commands refused (no license popups) | run_command, command_ui_open |
| Commands recorded as acting immediately / opening the browser need `confirm=true` (ask the user first) | run_command, command_ui_open |
| 2.5 s minimum gap between command launches; panels must stop changing before they are filled | run_command, command_ui_open |
| Wait until TBC is idle (no Compute Project window, not recalculating) before every command action and after every button press | all command_ui_* tools, tbc_wait_idle |
| Popups: only Cancel/Close/No are pressed, otherwise closed with X; license popups always X; progress windows never touched; one pass only | tbc_dialogs action=dismiss, safe_dismiss |
| WPF popups (e.g. "Feature Library Missing") are detected like normal dialogs | command_ui_*, tbc_dialogs |
| TBC error-report popups (buttons << / OK) are logged to `memory\tbc_errors.log` in the learned know-how folder and work stops | after every button press |
| Grid checkboxes / radio buttons are clicked like a user (setting them in code leaves TBC out of sync) | command_ui_fill, ui_grid |
| Deletion goes through TBC's own Delete command (also for layers) | delete_entities |
| Every job-database answer carries `reference_only` (the snapshot's date and the rule above); imports from the suite's shared knowledge folder are refused, and a scan shows each file's saved date | tbc_project_notes, tbc_import |

## Working rules

- **Create geometry with verified tools** (create_points, create_linestring) or TBC's own commands, not by adding
  raw CAD entity types through the API.
- **Delete with `delete_entities`** (TBC's Delete command), never by removing objects from containers in code.
- **Picker fields:** strings are typed as text (a point ID like `4700486` is not an object serial). Linking an object
  directly needs an integer serial that exists (WinForms and WPF pickers). Multi-select boxes ("Selected: N") take
  a list of serials. Coordinate boxes take point IDs (typed as real keystrokes). See linework_tools_usage.
- **Field order matters** in some panels: pick the object a panel works on before typing coordinates for it
  (Divide Area: Area to Divide before Origin/End point; the fill tool enforces this).
- Some tools only work with picks in the Plan View (Capture Outline, Fillet/Chamfer, Legal Description): ask the
  user to pick rather than forcing it.
- **Never press buttons on license popups** except to back out; licensing is the user's business.
- **Read popups before closing them**, and if TBC shows an error report, stop and tell the user.
- **Screenshots only of TBC.** `tbc_view screenshot` refuses when another application covers the view (it would
  capture that application's content). Never describe or keep an image that shows something other than TBC.
- Explode works on blocks only; Rotate's positive angle is clockwise; Change Elevation on a linestring stores a
  vertical element. See the cad_*, survey_* and linework skills for per-command details.
- Run the MCP server and helper scripts with **Python 3.12** (`py -3.12`); Python 3.15 failed inside html.parser.

## TBC versions: add, never delete

- Everything here was verified on **TBC 2026.10 (build 44.0.9666.28609)**. `bridge_status` reports the running
  release (`tbc.release`); skills, lessons, command layouts and scripts record theirs (`tbc_versions`,
  `tbc_version`), and search results / skill reads warn when they differ.
- When a newer release behaves differently: **add** knowledge for it, keep the old.
  - Skills: `tbc_skills action=append_version_section name=<skill> body=<what changed>` adds a
    `## TBC <release>` section (saving over a skill from another release is refused).
  - Lessons: add a new lesson (it is stamped with the running release); lessons from other releases cannot be deleted.
  - Command layouts: recorded automatically per release next to the 2026.10 layout.
  - Scripts: `tbc_script save overwrite=true` bumps `script_version`, adds the release to `tbc_versions` and keeps
    the previous version in `scripts\_archive\` of the learned know-how folder. Running a script made on another release returns a
    `version_note`.

## Licenses differ between users

- Each user's TBC license/subscription is different. Every time the MCP server starts it builds a **license profile**
  (licensed features + expiry, which commands are available, ~0.5 s) in `%LOCALAPPDATA%\TBC-MCP\license\<hash>.json`
  on that machine only. It is private, per-user data: never copy it into the knowledge base, skills or lessons.
  `tbc_license action=summary` shows it; `bridge_status` reports it.
- Every command is still checked live before it runs; unlicensed ones are refused without opening TBC's license popup.
- Skills and lessons may have been written on a machine with another license: `tbc_skills` search/read flags
  commands the current license lacks. Offer an alternative or name the missing feature instead.

## Where things are written down: three kinds of knowledge

Decide by what it is about, and ask the user before saving any of them:

1. **How to drive TBC** (a field quirk, which command does X, a verified procedure, a reusable script, the user's
   way of working) -> `tbc_memory`, `tbc_skills`, `tbc_script`, `tbc_preferences`. General: useful on any job.
   - Built-ins ship with TBC MCP in its `knowledge\` folder and are only read.
   - Everything learned on this PC is saved in the learned know-how folder (`TBC_MCP_KNOWLEDGE_DIR`, else the
     `tbc\` folder inside the suite's shared folder, `Documents\Project Knowledge`), never in the
     repository. A learned skill, script, command record, lesson or preference wins over the built-in one of the
     same name.
   - In both: `preferences.json` (the user's rules, sent to every AI in the server instructions),
     `memory\lessons.jsonl` (lessons with a command key appear when that command opens), `skills\**` (verified
     procedures: this file, cad_*, survey_*, linework_*, layer_manager, points, surfaces), `commands\*.json`
     (recorded panel layouts), `scripts\*.py` (saved scripts). TBC error popups go to `memory\tbc_errors.log` in
     the learned folder.
   - Keep project-specific details (client/project names, file names, real site coordinates) out of them: write
     "the test project" and use made-up example coordinates. The tools refuse text that names a job.
2. **Facts about this job** -> `tbc_project_notes`: the job's project database shared with Civil 3D MCP and
   Project Analyzer (`projects\<job>.db` in the shared folder, matched to the job by the .vce's folder). Link the
   TBC folder to the job's existing name when the other tools already know it. One fact per line, in the suite's
   reference formats (2026-10-03, 12+50, MH-3, C-104, RFI 12, CO 4, $12,500.00, John Smith (J. Smith)); the source
   (the open TBC project, or the user) is recorded for you. Only TBC's own facts may be updated or removed (remove
   retires them); correct another tool's fact by adding one with `supersedes`.
3. **Engineering or company practice true on every job** (design and survey standards, naming conventions) ->
   `tbc_practices`: `practices.json` in the shared folder, used by all three tools. Only TBC's own entries may be
   changed.

- License profiles are NOT knowledge: they stay in `%LOCALAPPDATA%\TBC-MCP\license` on each machine. Never put
  license details, licensee or company names, user-profile paths or tokens in a fact, practice or lesson.
