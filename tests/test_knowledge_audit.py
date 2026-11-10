# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Audit: no job data in the repository's general knowledge (suite contract, rule 8). Scans every file under knowledge\\
that git tracks with the same rules the knowledge base applies before saving (knowledge.job_data_problems): absolute
paths outside program/system folders, user-profile paths, TBC project and job file names, and the names of the jobs
in this computer's shared projects folder (read only, if it exists). Fails listing file and line for every hit.
Usage: python test_knowledge_audit.py

Needs TBC
    No. Offline. Needs git (it asks `git ls-files` what is tracked): git on PATH, else GitHub Desktop's bundled
    git, else Git for Windows (find_git). Without any, it prints a FAIL line saying so and exits 1 before checking
    anything. It reads the shared folder's project databases only to learn the job names (knowledge._job_names),
    and writes nothing.

How to run
    py -3.12 tests\\test_knowledge_audit.py
PASS/FAIL lines; exit code 0 when no hit, else 1.
"""
import glob, os, re, shutil, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
repo = os.path.normpath(os.path.join(here, ".."))
sys.path.insert(0, os.path.join(repo, "mcp_server"))
import knowledge as K  # noqa: E402


def find_git():
    """Path of git.exe: on PATH, else the newest GitHub Desktop's bundled git, else Git for Windows; None if none.
    (Same lookup as tests\\test_knowledge_split.py; GitHub Desktop doesn't put its git on PATH.)"""
    found = shutil.which("git")
    if found:
        return found
    desktop = glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "GitHubDesktop", "app-*", "resources", "app", "git", "cmd", "git.exe"))
    # newest app-<version> first, compared as numbers (app-3.4.10 is newer than app-3.4.9)
    desktop.sort(key=lambda p: [int(n) for n in re.findall(r"\d+", p.split(os.sep + "GitHubDesktop" + os.sep)[-1].split(os.sep)[0])], reverse=True)
    others = [os.path.join(os.environ.get(v, ""), "Git", "cmd", "git.exe") for v in ("ProgramFiles", "ProgramFiles(x86)")]
    return next((c for c in desktop + others if os.path.isfile(c)), None)


git = find_git()
if not git:
    print("FAIL git not found (not on PATH, no GitHub Desktop or Git for Windows): put git on PATH and run again; nothing was checked")
    sys.exit(1)

# The jobs this computer knows about, read without touching anything (no folder move, no writes)
shared = K.shared_dir()
names = K._job_names(shared) if os.path.isdir(shared) else set()

tracked = subprocess.run([git, "ls-files", "-z", "knowledge"], cwd=repo, capture_output=True, check=True).stdout
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
