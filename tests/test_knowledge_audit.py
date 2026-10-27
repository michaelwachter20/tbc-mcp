# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Audit: no job data in the repository's general knowledge (suite contract, rule 8). Scans every file under knowledge\
that git tracks with the same rules the knowledge base applies before saving (knowledge.job_data_problems): absolute
paths outside program/system folders, user-profile paths, TBC project and job file names, and the names of the jobs
in this computer's shared projects folder (read only, if it exists). Fails listing file and line for every hit.
Usage: python test_knowledge_audit.py
"""
import os, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
repo = os.path.normpath(os.path.join(here, ".."))
sys.path.insert(0, os.path.join(repo, "mcp_server"))
import knowledge as K  # noqa: E402

# The jobs this computer knows about, read without touching anything (no folder move, no writes)
shared = K.shared_dir()
names = K._job_names(shared) if os.path.isdir(shared) else set()

tracked = subprocess.run(["git", "ls-files", "-z", "knowledge"], cwd=repo, capture_output=True, check=True).stdout
files = [f for f in tracked.decode("utf-8").split("\0") if f]
hits = []
for rel in files:
    try:
        with open(os.path.join(repo, rel), "r", encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        continue  # binary files hold no text to check
    for n, line in enumerate(lines, 1):
        for problem in K.job_data_problems(line, names):
            hits.append("%s:%d: %s" % (rel, n, problem))

print("checked %d tracked files under knowledge\\ against %d job name(s)" % (len(files), len(names)))
for h in hits:
    print("FAIL " + h)
print("PASS no job data in knowledge\\" if not hits else "%d hit(s): generalize them or move job facts to tbc_project_notes" % len(hits))
sys.exit(1 if hits else 0)
