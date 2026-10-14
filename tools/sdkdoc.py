# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""Search the TBC SDK XML docs. Usage: python sdkdoc.py <regex> [--members] [--max N]
Matches against member ids (T:/M:/P:/F:/E:) and prints id + summary."""
import sys, re, glob, os, pickle
import xml.etree.ElementTree as ET

SDK = r"C:\Program Files (x86)\Trimble\Macros SDK"
CACHE = os.path.join(os.path.dirname(__file__), "sdkdoc.pkl")

def load():
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
    args = sys.argv[1:]
    mx = 200
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
