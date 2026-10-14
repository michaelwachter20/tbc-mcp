---
name: layer_manager
tbc_versions: ["2026.10"]
category: layers
description: "Use TBC's Layer Manager pane: read all layers, rename, set line weight / display priority / group, toggle Print and Protect, add a layer with New Layer, delete a layer with the red X."
requires_write: true
parameters: []
verified: "2026-10-13 on TBC 2026.10 with throwaway layers MCP_LM_TEST / MCP_NEWBTN_TEST (all changes confirmed in the model, then removed)"
---

> Verified on TBC 2026.10. If something here does not work on a newer TBC release, ADD a section '## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or rewrite the 2026.10 information.

## Open it

Layer Manager is a dockable **pane**, not a command panel. `run_command key=layermanager` toggles it
(running it again closes it). Check `command_ui_inspect scope="pane:Layer Manager"`; its `panes` list shows
whether it is open.

## The grid

`ui_grid action=read scope="pane:Layer Manager"` (optionally `where={"LayerName": "X"}`). One row per layer:

| column (name) | header | kind | how to change |
|---|---|---|---|
| LayerName | Layer Name | text | `ui_grid action=set column="Layer Name" value=...` (renames the layer) |
| LayerColor | Layer Color | colour picker | not automated yet; use `set_properties` or execute_python (`layer.DefaultColor`) |
| LineStyle | Line Style | style picker | not automated yet |
| LineWeight | Line Weight | dropdown | `set value="0.50 mm"` (option text) |
| Protect | Protect | checkbox | `set value=true/false` (done with a real click) |
| Group | Group Layer | dropdown | `set value=<group name>` |
| DisplayPriority | Display Priority | dropdown | `set value="Normal"` etc. |
| Print | Print | checkbox | `set value=true/false` (real click) |
| Delete | (red X) | icon | `ui_grid action=click column=Delete row={"LayerName": "X"}` |
| EditColumn / GroupColor | - | icons | ignore |

Pane controls: `layerFilter` (text filter), `groupFilterCombo` (All layers / groups), buttons **New Layer**,
**Import**, **Export**, **Close** (`command_ui_click scope="pane:Layer Manager" button="New Layer"`).
New Layer adds a layer literally named "New Layer"; rename it right away.

## Gotchas

- **Checkboxes only reach the model through a real click.** Setting the cell value programmatically changes
  the grid display but not the layer. `ui_grid action=set` handles this automatically.
- Rows are matched by column values and must match exactly one row; the row is re-verified right before any
  click, so a red X can never hit a different layer.
- Deleting an empty layer gives no confirmation popup. Layers with objects may ask; read `after.dialogs`.
- Always confirm with the user before deleting real layers; verify with `list_layers` afterwards.
- For bulk work the API is simpler: `create_layer`, `set_properties` (Layer serial), `Layer.FindLayer(prj, name)`.
- **Deleting layers:** prefer `delete_entities serials=[<layer serial>]` (selects the layer and runs TBC's Delete
  command). The red-X click worked earlier but stopped working when the pane was too narrow for the Delete column.
