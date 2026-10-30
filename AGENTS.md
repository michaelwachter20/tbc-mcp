# Guide for AI coding assistants

Read [CLAUDE.md](CLAUDE.md): it is the guide for any AI assistant or developer changing this repository (where
things are, how to check a change, the rules). The short version:

- Every code file keeps its TBC version header as line 1; for a newer TBC, add handling and keep the old behavior.
- No job data in the repository: `knowledge\` holds general know-how only and is never written at runtime.
- Run the five offline tests in CLAUDE.md before committing.
- Be gentle with TBC: go through the safety helpers, never press license popups or cancel progress windows.
