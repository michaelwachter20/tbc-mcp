# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Search the TBC SDK XML docs. Usage: python sdkdoc.py <regex> [--max N]
Matches against member ids (T:/M:/P:/F:/E:) and prints id + summary.

Developer tool (not shipped in the release zip). Searches the .NET XML documentation files of the Trimble
Macros SDK: every <member name="T:...|M:...|P:...|F:...|E:..."> entry (type, method, property, field, event)
with its <summary>. The MCP server's search_sdk_docs tool covers the same docs for the AI; this is the
command-line version. The README notes the SDK reference is from an older TBC release, and the installed TBC
help (tbc_help) is the more reliable guide.

Needs TBC
    No. Needs the Macros SDK docs: TBC_SDK_DOCS when set (as for the MCP server), else the default install
    folder below.

How to run
    py -3.12 tools\\sdkdoc.py "Point\\.CreatePoint"
    py -3.12 tools\\sdkdoc.py "^T:Trimble\\.Vce\\.Core" --max 50
    The pattern is a Python regex matched (re.search) against the member id. --max N caps the output
    (default 200).

What it writes
    tools\\sdkdoc.pkl, a pickle cache of all (assembly, member id, summary) rows (in .gitignore: rebuilt locally
    from each user's own SDK install). It is rebuilt when an SDK .xml file is newer than the cache or the docs
    folder changed, and an empty result (no SDK found) is never cached.

Output
    One line per match: "[<assembly>] <member id>  -- <summary, first 200 chars>", then "...more" when the
    --max limit was hit.
"""
import sys, re, glob, os, pickle
import xml.etree.ElementTree as ET

SDK = os.environ.get("TBC_SDK_DOCS") or r"C:\Program Files (x86)\Trimble\Macros SDK"
CACHE = os.path.join(os.path.dirname(__file__), "sdkdoc.pkl")

def load():
    """All (assembly name, member id, summary) rows from the SDK's *.xml files, cached in CACHE.

    The cache records which folder it was built from; it is used only when that is still SDK and no .xml file
    there is newer than it. Files that aren't valid XML are skipped. A summary's text is flattened to one line
    with single spaces. Nothing is cached when no docs were found, so installing the SDK later just works.
    """
    files = glob.glob(os.path.join(SDK, "*.xml"))
    if os.path.exists(CACHE) and files and max(os.path.getmtime(f) for f in files) <= os.path.getmtime(CACHE):
        try:
            with open(CACHE, "rb") as f:
                cached = pickle.load(f)
            # caches from before this check are a bare list of rows: rebuild those
            if isinstance(cached, dict) and cached.get("sdk") == SDK:
                return cached["rows"]
        except Exception:
            pass  # unreadable cache: rebuild it
    rows = []
    for fn in files:
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
    if rows:
        with open(CACHE, "wb") as f:
            pickle.dump({"sdk": SDK, "rows": rows}, f)
    return rows

def main():
    """Parse the command line (regex, optional --max N) and print the matching members."""
    args = sys.argv[1:]
    mx = 200
    # take "--max N" out of the argument list so args[0] is the pattern
    if "--max" in args:
        i = args.index("--max"); mx = int(args[i + 1]); del args[i:i + 2]
    if not args:
        sys.exit("Usage: python sdkdoc.py <regex> [--max N]")
    rows = load()
    if not rows:
        sys.exit("No SDK XML docs found in %s (set TBC_SDK_DOCS to the Macros SDK folder)." % SDK)
    pat = re.compile(args[0])
    n = 0
    for asm, name, summ in rows:
        if pat.search(name):
            print(f"[{asm}] {name}" + (f"  -- {summ[:200]}" if summ else ""))
            n += 1
            if n >= mx:
                print("...more"); break

main()
