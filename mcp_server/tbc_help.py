# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Offline search over TBC's installed help (HTML topics). A command's help page is <HelpTopic>.htm.
Override the folder with TBC_HELP_DIR (default: English 'iv' help of the TBC install).
"""
import html
import os
import re
from html.parser import HTMLParser

HELP_DIR = os.environ.get("TBC_HELP_DIR") or r"C:\Program Files\Trimble\Trimble Business Center Help\iv\Help"
_index = None


class _Text(HTMLParser):
    SKIP = {"script", "style", "head"}
    BLOCK = {"p", "li", "tr", "h1", "h2", "h3", "h4", "div", "br", "table", "td"}

    def __init__(self):
        HTMLParser.__init__(self)
        self.parts, self.skip, self.title, self.keywords, self._in_title = [], 0, "", "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            a = dict(attrs)
            if (a.get("name") or "").lower() == "keywords":
                self.keywords = a.get("content") or ""
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


_TAG = re.compile(r"<[^>]+>")


def parse(path):
    """Plain-text view of a help page. Regex-based on purpose: html.parser crashed CPython 3.15
    ('Fatal Python error: _TAIL_CALL_CACHE') on these pages."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    m = re.search(r"<title>(.*?)</title>", raw, re.S | re.I)
    title = html.unescape(m.group(1)).strip() if m else ""
    m = re.search(r'<meta\s+name="Keywords"\s+content="([^"]*)"', raw, re.I)
    keywords = html.unescape(m.group(1)) if m else ""
    body = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", raw)
    body = re.sub(r"(?i)<li\b[^>]*>", "\n- ", body)
    body = re.sub(r"(?i)<(?:p|tr|h\d|div|br|table|td)\b[^>]*>", "\n", body)
    text = html.unescape(_TAG.sub("", body))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    # drop the navigation boilerplate at the top (Back/Forward/Print/Related topics)
    text = re.sub(r"^(?:\s*(?:Back|Forward|Previous Topic|Next Topic|Print|Related Topics)\s*\n?)+", "", text)
    return {"title": title, "keywords": keywords.strip(), "text": text.lstrip("﻿")}


def _load():
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
    path = os.path.join(HELP_DIR, "%s.htm" % str(tid).replace(".htm", ""))
    if not os.path.exists(path):
        return None
    d = parse(path)
    d["topic"] = str(tid)
    d["text"] = d["text"][:max_chars]
    return d


def search(query, limit=15):
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
