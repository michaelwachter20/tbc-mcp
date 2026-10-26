# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""One-off development probe: call the macro's Setup() entry point outside TBC.

Setup(cmdData, macroFileFolder) in tbc_macro\\TbcMcpBridge.py is what TBC calls to register the ribbon button.
Here an empty stand-in object plays cmdData, so the probe shows which caption and image Setup assigns, that
_update_ribbon() returns cleanly outside TBC, and the last line the macro wrote to its log
(%TEMP%\\tbc_mcp_bridge.log).

Needs TBC
    No running TBC, but TBC's IronPython 3.4 and DLLs from the TBC install (it imports the bridge macro).

How to run
    powershell -ExecutionPolicy Bypass -File tests\\dev\\run_ipy.ps1 tests\\dev\\ipy_setup_check.py

Output / pass
    Three console lines, read by eye; an exception means Setup is broken.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "..", "..", "tbc_macro"))
import TbcMcpBridge as B
# a bare object standing in for TBC's command description; Setup sets attributes on it
class Cmd(object): pass
c = Cmd()
B.Setup(c, ".")
print("Setup ok; caption:", c.ShortCaption, "| image:", c.ImageSmall.Width, "px")
print("update_ribbon outside TBC returns:", B._update_ribbon(False))
print("log tail:", open(B.LOG_FILE).read().strip().splitlines()[-1])
