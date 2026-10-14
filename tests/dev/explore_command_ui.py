# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Exploration helper: open a TBC command and dump its panel's control tree (read-only).
Usage: python explore_command_ui.py <command_key> [--cancel]"""
import sys, os, time, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "mcp_server"))
import tbc_mcp_server as S

key = sys.argv[1]
if key != "-":
    S.call_bridge("run_command", {"key": key})
    time.sleep(2.5)

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
r = S.call_bridge("execute_python", {"code": code, "transaction": False})
print(r["stdout"])
if "--cancel" in sys.argv:
    S.call_bridge("execute_python", {"code": "TrimbleOffice.TheOffice.MainForm.CommandHost.CloseAll()", "transaction": False})
    print("closed")

