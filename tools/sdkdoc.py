# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Search the TBC SDK XML docs. Usage: python sdkdoc.py <regex> [--members] [--max N]
Matches against member ids (T:/M:/P:/F:/E:) and prints id + summary.

Developer tool (not shipped in the release zip). Searches the .NET XML documentation files of the Trimble
Macros SDK: every <member name="T:...|M:...|P:...|F:...|E:..."> entry (type, method, property, field, event)
with its <summary>. The MCP server's search_sdk_docs tool covers the same docs for the AI; this is the
command-line version. The README notes the SDK reference is from an older TBC release, and the installed TBC
help (tbc_help) is the more reliable guide.

Needs TBC
    No. Needs the Macros SDK installed at the fixed path below (this script does not read TBC_SDK_DOCS).

How to run
    py -3.12 tools\\sdkdoc.py "Point\\.CreatePoint"
    py -3.12 tools\\sdkdoc.py "^T:Trimble\\.Vce\\.Core" --max 50
    The pattern is a Python regex matched (re.search) against the member id. --max N caps the output
    (default 200). The --members flag in the usage line isn't implemented: main() never looks for it.

What it writes
    tools\\sdkdoc.pkl, a pickle cache of all (assembly, member id, summary) rows, built on the first run and
    reused after that (in .gitignore: rebuilt locally from each user's own SDK install). The cache is never
    refreshed, so delete it after installing or updating the SDK; a run without the SDK caches an empty list.

Output
    One line per match: "[<assembly>] <member id>  -- <summary, first 200 chars>", then "...more" when the
    --max limit was hit.
"""
import sys, re, glob, os, pickle
import xml.etree.ElementTree as ET

SDK = r"C:\Program Files (x86)\Trimble\Macros SDK"
CACHE = os.path.join(os.path.dirname(__file__), "sdkdoc.pkl")

def load():
    """All (assembly name, member id, summary) rows from the SDK's *.xml files, cached in CACHE.

    Files that aren't valid XML are skipped. A summary's text is flattened to one line with single spaces.
    """
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    rows = []
    for fn in glob.glob(os.path.join(SDK, "*.xml")):
        try:
            root = ET.parse(fn).getroot()
        except Exception:
            continue
        asm = root.findtext("assembly/name") or ""
        for m in root.iter("member"):
            name = m.get("name", "")
            s = m.find("summary")
            summ = " ".join("".join(s.itertext()).split()) if s is not None else ""
            rows.append((asm, name, summ))
    with open(CACHE, "wb") as f:
        pickle.dump(rows, f)
    return rows

def main():
    """Parse the command line (regex, optional --max N) and print the matching members."""
    args = sys.argv[1:]
    mx = 200
    # take "--max N" out of the argument list so args[0] is the pattern
    if "--max" in args:
        i = args.index("--max"); mx = int(args[i + 1]); del args[i:i + 2]
    pat = re.compile(args[0])
    n = 0
    for asm, name, summ in load():
        if pat.search(name):
            print(f"[{asm}] {name}" + (f"  -- {summ[:200]}" if summ else ""))
            n += 1
            if n >= mx:
                print("...more"); break

main()
