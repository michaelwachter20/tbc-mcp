---
name: reusable_script_pattern
tbc_versions: ["2026.10"]
category: workflows
description: "When and how to save a reusable TBC script with tbc_script (parameters, read/write mode, dry runs)."
requires_write: false
parameters: []
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

## When to save a script

Save once a snippet has worked on a real project and the task is likely to recur (renaming, relayering, reports,
QC checks, exports). Search first: `tbc_skills action=search query=...` (also finds scripts).

## Template

```python
# `args` holds the declared parameters (defaults applied). Globals: prj, wv, bridge, TbcPoint, Point3D,
# Layer, Model3D, GlobalSelection, TrimbleOffice, clr, ... (same as execute_python).
f = bridge.factor(prj)
dry = args.get("dry_run", True)
changed = []
for pt in TbcPoint.GetAllPoints(prj):
    try:
        ...                       # decide per item
        if not dry:
            ...                   # change it
        changed.append(str(pt.Name))
    except Exception as ex:
        print("skipped %s: %s" % (pt.Name, ex))   # skip bad items, don't abort the run
print("%s %d items" % ("would change" if dry else "changed", len(changed)))
result = {"count": len(changed), "sample": changed[:20], "dry_run": dry}
```

## Checklist

- Declare every input in `parameters` with a type and default; keep names snake_case.
- `mode: read` for reports/checks, `write` for anything that changes the project (one undo step, rolls back on error).
- Destructive scripts take `dry_run` (boolean, default true); run dry first and show the user the result.
- Return compact results (counts, samples), not whole objects.
- Once proven, promote to a skill (`tbc_skills action=save`) with the rules and gotchas you discovered.
