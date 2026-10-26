# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Offline search over TBC's installed help (HTML topics). A command's help page is <HelpTopic>.htm.
Override the folder with TBC_HELP_DIR (default: English 'iv' help of the TBC install).

Used by
    the MCP server's tbc_help tool (t_help in tbc_mcp_server.py: action=search -> search(), action=read ->
    topic(), where a command key is first turned into its HelpTopic by asking TBC) and by the ribbon-tab
    surveyor tests\\tab_survey.py (help title and summary per tool). The README calls the installed help
    (~3,500 topics) the more reliable guide than the older Macros SDK reference.

Needs TBC
    No running TBC: it only reads the .htm files of the installed help. If HELP_DIR doesn't exist, search()
    returns nothing and topic() returns None.

Standard library only, like the rest of the server.
"""
import html
import os
import re

HELP_DIR = os.environ.get("TBC_HELP_DIR") or r"C:\Program Files\Trimble\Trimble Business Center Help\iv\Help"
# search index, built on first use by _load() and kept for the life of the process:
# list of (topic id = file name without .htm, title, keywords, lower-cased text)
_index = None


# any HTML tag (or comment), removed after the block tags have been turned into line breaks
_TAG = re.compile(r"<[^>]+>")


def parse(path):
    """Plain-text view of a help page. Regex-based on purpose: html.parser crashed CPython 3.15
    ('Fatal Python error: _TAIL_CALL_CACHE') on these pages.

    Returns {"title", "keywords", "text"}: the <title>, the content of <meta name="Keywords">, and the page
    text with tags removed, list items as "- " lines and one line break per paragraph/row/heading/cell.
    Undecodable bytes are replaced rather than raising.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    m = re.search(r"<title>(.*?)</title>", raw, re.S | re.I)
    title = html.unescape(m.group(1)).strip() if m else ""
    m = re.search(r'<meta\s+name="Keywords"\s+content="([^"]*)"', raw, re.I)
    keywords = html.unescape(m.group(1)) if m else ""
    # remove whole script/style/head elements (\1 matches the same closing tag), then turn list items and
    # block-level opening tags into line breaks before every remaining tag is stripped
    body = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", raw)
    body = re.sub(r"(?i)<li\b[^>]*>", "\n- ", body)
    body = re.sub(r"(?i)<(?:p|tr|h\d|div|br|table|td)\b[^>]*>", "\n", body)
    text = html.unescape(_TAG.sub("", body))
    # collapse runs of spaces/tabs (not newlines), then runs of blank lines
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    # drop the navigation boilerplate at the top (Back/Forward/Print/Related topics)
    text = re.sub(r"^(?:\s*(?:Back|Forward|Previous Topic|Next Topic|Print|Related Topics)\s*\n?)+", "", text)
    # the lstrip below removes a leading byte-order mark (U+FEFF) left in the text
    return {"title": title, "keywords": keywords.strip(), "text": text.lstrip("﻿")}


def _load():
    """Parse every .htm file in HELP_DIR once and cache the rows in _index (see there).

    Pages that fail to parse are skipped. The first search pays for reading all topics; later searches reuse
    the cache. An index built while HELP_DIR was missing stays empty until the process restarts.
    """
    global _index
    if _index is not None:
        return _index
    rows = []
    if os.path.isdir(HELP_DIR):
        for fn in os.listdir(HELP_DIR):
            if fn.endswith(".htm"):
                try:
                    d = parse(os.path.join(HELP_DIR, fn))
                except Exception:
                    continue
                rows.append((fn[:-4], d["title"], d["keywords"], d["text"].lower()))
    _index = rows
    return rows


def topic(tid, max_chars=6000):
    """One help topic by id ("1234" or "1234.htm"): parse() result plus "topic", text cut to max_chars.

    Returns None when HELP_DIR has no such file. Read straight from disk (no index needed).
    """
    path = os.path.join(HELP_DIR, "%s.htm" % str(tid).replace(".htm", ""))
    if not os.path.exists(path):
        return None
    d = parse(path)
    d["topic"] = str(tid)
    d["text"] = d["text"][:max_chars]
    return d


def search(query, limit=15):
    """Rank help topics for a free-text query; returns up to `limit` [{"topic", "title"}], best first.

    The query is split into lower-case words (single characters dropped). Score per word: 10 per hit in the
    title, 5 per hit in the keywords, plus up to 5 for hits in the text (substring counts, so "line" also
    matches "linestring"). A topic containing every word somewhere gets 20 extra. Topics scoring 0 are left
    out.
    """
    words = [w for w in re.split(r"\W+", query.lower()) if len(w) > 1]
    hits = []
    for tid, title, kw, text in _load():
        tl, kl = title.lower(), kw.lower()
        s = sum(10 * tl.count(w) + 5 * kl.count(w) + min(text.count(w), 5) for w in words)
        if words and all(w in tl or w in kl or w in text for w in words):
            s += 20
        if s:
            hits.append((s, tid, title))
    hits.sort(key=lambda h: -h[0])
    return [{"topic": t, "title": ti} for _, t, ti in hits[:limit]]
