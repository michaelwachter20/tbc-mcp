# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "..", "..", "tbc_macro"))
import TbcMcpBridge as B
out = os.path.dirname(os.path.abspath(sys.argv[0]))
for on in (True, False):
    for s in (16, 32):
        B._status_icon(s, on).Save(os.path.join(out, "icon_%s_%d.png" % ("on" if on else "off", s)))
B._update_ribbon(True, 1)  # must not raise outside TBC
print("icons written")
