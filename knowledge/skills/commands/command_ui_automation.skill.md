---
name: command_ui_automation
tbc_versions: ["2026.10"]
category: commands
description: "How to drive any TBC command panel (fill the boxes a user would click into, press Add/Apply/OK, answer popups) with the command_ui_* tools."
requires_write: true
parameters: []
verified: "2026-10-13 on Create Point (addpoint), including duplicate-ID popup"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

## When to use

When a task is only exposed as a TBC command with a panel (most of the ribbon), or when the panel applies logic
the raw API doesn't (feature-code processing, defaults, validation). For plain data creation the API tools
(create_points, create_linestring, ...) are faster and need no UI.

## Steps

1. `tbc_skills action=search` for the command - a skill or remembered panel may already describe it.
2. `list_commands contains=<word>` to find the key, then `command_ui_open key=<key>`.
   Read `fields` (label, kind, value, options), `buttons`, and `remembered` notes.
3. `command_ui_fill values=[[label, value], ...] press=<button>`:
   - fill **in the order a user would** (top to bottom); later fields can depend on earlier ones;
   - type values exactly as a user would, in display units (`10500`, `6.5`);
   - dropdowns take the option text (must be in `options`); checkboxes take true/false.
4. Check the response: each field's `now` value (TBC reformats, e.g. `10500.000`), `warning`s, and `after`:
   - `after.dialogs` = a popup is waiting -> read `message`, then `tbc_dialogs action=click button=Yes|No|OK`;
   - `after.field_status` = TBC rejected a value.
5. Verify with read tools (list_points, get_entity, ...). Many panels stay open after Add/Apply and auto-advance
   values (Create Point increments the Point ID) - you can fill again for the next item.
6. `command_ui_close` when done.
7. Record anything non-obvious: `tbc_memory action=add command=<key> text=...`.

## Gotchas

- Fields of type `text` with a `control` like `SelectPlanar1` / `ElevationEdit` are TBC coordinate boxes; they
  accept typed numbers and show `?` when empty.
- Fields inside collapsed sections are hidden from `command_ui_open`; pass `include_hidden=true` to see them.
- Popups are TBC `InternalMessageBox` forms (scope `dialog:0`) or standard Windows dialogs (`native: true`).
- Buttons are pressed asynchronously so a popup can never hang the bridge; always look at `after`.
- Ask the user before pressing buttons that commit big or irreversible changes.
