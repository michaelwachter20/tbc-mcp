# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "..", "..", "tbc_macro"))
import TbcMcpBridge as B
class Cmd(object): pass
c = Cmd()
B.Setup(c, ".")
print("Setup ok; caption:", c.ShortCaption, "| image:", c.ImageSmall.Width, "px")
print("update_ribbon outside TBC returns:", B._update_ribbon(False))
print("log tail:", open(B.LOG_FILE).read().strip().splitlines()[-1])
