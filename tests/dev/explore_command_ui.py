# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Exploration helper: open a TBC command and dump its panel's control tree (read-only).
Usage: python explore_command_ui.py <command_key> [--cancel]

One-off development probe (tests\\dev\\), not part of any test suite. It was used to learn how TBC builds its
command panels (WinForms controls with embedded WPF content) while writing the panel engine
mcp_server\\ipy\\command_ui.py.

Needs TBC
    Yes: TBC 2026.10 with a project open and the MCP Bridge macro on.

How to run
    py -3.12 tests\\dev\\explore_command_ui.py <command_key>          run the command, then dump its panel
    py -3.12 tests\\dev\\explore_command_ui.py -                      dump whatever panel is open now
    add --cancel to close all open commands afterwards (CommandHost.CloseAll)
    The command is launched directly through the bridge's run_command, without the server's license check
    or pacing, so use keys you know are licensed and safe to open.

Output
    Console: the open command object's properties, then the control tree (up to 600 lines). "F" lines are
    WinForms controls, "W" lines WPF elements found inside ElementHost controls, each with its type, Name and
    a few value properties (Text, Content, IsChecked, SelectedItem ...). Nothing is applied or saved.
"""
import sys, os, time, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "mcp_server"))
import tbc_mcp_server as S

key = sys.argv[1]
# "-" means: don't launch anything, just inspect the panel that is already open
if key != "-":
    S.call_bridge("run_command", {"key": key})
    # give TBC time to build the panel before reading it
    time.sleep(2.5)

# IronPython run inside TBC. Loads the WinForms/WPF assemblies, prints the top command's properties, then walks
# the CommandHost: WinForms children through .Controls (wf), and for each ElementHost its WPF child through
# the logical tree, falling back to the visual tree when an element has no logical children (wpf). Depth is
# capped at 40 and WPF nodes are de-duplicated by id() to avoid cycles.
code = r"""
clr.AddReference('System.Windows.Forms'); clr.AddReference('WindowsFormsIntegration'); clr.AddReference('PresentationFramework'); clr.AddReference('PresentationCore')
from System.Windows import LogicalTreeHelper, DependencyObject, FrameworkElement
from System.Windows.Media import VisualTreeHelper, Visual
ch = TrimbleOffice.TheOffice.MainForm.CommandHost
cmd = ch.TopCommand
print('TopCommand:', cmd, '|', cmd.GetType().FullName if cmd else None)
if cmd is not None:
    for p in cmd.GetType().GetProperties():
        if p.GetIndexParameters().Length: continue
        try: v = p.GetValue(cmd, None)
        except: v = '<err>'
        print('  cmd.%s : %s = %s' % (p.Name, p.PropertyType.Name, str(v)[:80]))
VALS = ('Text', 'Content', 'IsChecked', 'SelectedItem', 'SelectedIndex', 'Value', 'Header', 'Caption', 'SelectedName', 'SelectedSerialNumber', 'Elevation', 'Coordinate')
lines = []
def desc(o):
    t = o.GetType()
    s = t.FullName
    n = getattr(o, 'Name', '') or ''
    extra = []
    for a in VALS:
        try:
            if t.GetProperty(a) is None: continue
            v = getattr(o, a)
            if v is None or (hasattr(v, 'GetType') and v.GetType().IsSubclassOf(clr.GetClrType(DependencyObject)) and a == 'Content'): continue
            extra.append('%s=%r' % (a, str(v)[:50]))
        except: pass
    return '%s name=%r %s' % (s, n, ' '.join(extra))
def wpf(o, d, seen):
    if d > 40 or id(o) in seen: return
    seen.add(id(o))
    lines.append('  ' * d + 'W ' + desc(o))
    kids = []
    try:
        for c in LogicalTreeHelper.GetChildren(o):
            if isinstance(c, DependencyObject): kids.append(c)
    except: pass
    if not kids and isinstance(o, Visual):
        try:
            for i in range(VisualTreeHelper.GetChildrenCount(o)): kids.append(VisualTreeHelper.GetChild(o, i))
        except: pass
    for c in kids: wpf(c, d + 1, seen)
def wf(c, d):
    if d > 40: return
    lines.append('  ' * d + 'F ' + desc(c))
    if c.GetType().Name == 'ElementHost' and c.Child is not None:
        wpf(c.Child, d + 1, set())
    for k in c.Controls: wf(k, d + 1)
wf(ch, 0)
print('\n'.join(lines[:600]))
"""
# transaction False: read-only, no undo step; the dump comes back as the script's printed output
r = S.call_bridge("execute_python", {"code": code, "transaction": False})
print(r["stdout"])
if "--cancel" in sys.argv:
    S.call_bridge("execute_python", {"code": "TrimbleOffice.TheOffice.MainForm.CommandHost.CloseAll()", "transaction": False})
    print("closed")

