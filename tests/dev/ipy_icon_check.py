# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""One-off development probe: render the ribbon button's status icons and check the ribbon update is safe
outside TBC.

Probes _status_icon() and _update_ribbon() in tbc_macro\\TbcMcpBridge.py (the green / red "MCP Bridge"
light).

Needs TBC
    No running TBC, but TBC's IronPython 3.4 and DLLs from the TBC install (it imports the bridge macro).

How to run
    powershell -ExecutionPolicy Bypass -File tests\\dev\\run_ipy.ps1 tests\\dev\\ipy_icon_check.py

What it writes
    icon_on_16.png, icon_on_32.png, icon_off_16.png, icon_off_32.png next to this script (not cleaned up;
    *.png is in .gitignore) to look at by eye. Prints "icons written" when _update_ribbon didn't raise.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "..", "..", "tbc_macro"))
import TbcMcpBridge as B
# the PNGs go next to this script
out = os.path.dirname(os.path.abspath(sys.argv[0]))
# both states (on = green, off = red) in both ribbon sizes (16 px small image, 32 px large image)
for on in (True, False):
    for s in (16, 32):
        B._status_icon(s, on).Save(os.path.join(out, "icon_%s_%d.png" % ("on" if on else "off", s)))
B._update_ribbon(True, 1)  # must not raise outside TBC
print("icons written")
