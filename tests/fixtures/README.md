# Test fixtures

Copies of Project Analyzer's test job, so the offline tests run without that repository:

| File here | Copied from (project-analyzer repository) |
|---|---|
| `fixture.db` | `schema/fixture.db`: a small project database of a made-up job ("Elm Street Drainage", John Smith, MH-3, sheet C-104; no real job data), built by `schema/make_fixture.py` |
| `fixture-practices.json` | `schema/fixture-practices.json`: two good practices |
| `../../mcp_server/project-db.sql` | `schema/project-db.sql`: the table layout TBC MCP runs when it creates a job's database |

Copied at project-analyzer commit `936bc9e` ("Suite knowledge contract: one compressed project database per job").
`tests/test_project_knowledge.py` fails when any of the three differs from the analyzer's file, if that repository is
next to this one (else it prints SKIP). When the schema changes, rebuild the fixture there
(`python schema/make_fixture.py`) and copy all three again. The tests work on temporary copies; these files are
never changed.
