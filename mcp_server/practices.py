# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Good practices shared by the whole suite (Project Analyzer, Civil 3D MCP, TBC MCP): <shared>\\practices.json.

Engineering and company practice that doesn't depend on a program and holds on every job: "storm pipe minimum slope
0.5%", "label structures MH-n", "survey in NAD83 Illinois East". Not how to drive TBC (that is TBC's own know-how,
knowledge.py) and not facts about one job (the project database, projects.py). The contract is project-analyzer's
docs/suite-knowledge.md:

    {"practices": [{"id": "practice-1", "practice": "...", "topics": [...], "source": "civil3d",
                    "added": "<toISOString>", "updated"?: ..., "retired"?: ...}]}

Rules kept here: practice-N ids are never reused (removing sets "retired"); one line each; duplicate check (any case)
before adding; TBC changes only entries whose source is "tbc"; fields TBC doesn't know are kept; the file is re-read
right before every write and written atomically (temp file in the same folder, then rename), UTF-8 without BOM, LF,
2-space indent; a file that doesn't parse is never rewritten. The current practices are shown to the AI at the start
of a session, next to the user's preferences (practices_text).
"""
import json
import os
import re
import time

import knowledge as K
import projects as P

SOURCE = "tbc"
MAX_SHOWN = 100  # practices listed in the server instructions


def path():
    """<shared>\\practices.json."""
    return os.path.join(K.shared_root(), "practices.json")


def _load():
    """The file as written by any tool (every field kept), or {"practices": []} when it doesn't exist. Raises
    KnowledgeError when it can't be read or isn't the expected shape, so it is never rewritten then."""
    p = path()
    if not os.path.exists(p):
        return {"practices": []}
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError) as ex:
        raise K.KnowledgeError("%s can't be read (%s), so it isn't changed. Fix or restore it first." % (p, ex))
    if not isinstance(data, dict) or not isinstance(data.get("practices", []), list):
        raise K.KnowledgeError("%s isn't a practices file ({\"practices\": [...]}), so it isn't changed." % p)
    data.setdefault("practices", [])
    return data


def _save(data):
    """Write atomically: a temp file in the same folder, then rename over the target. UTF-8 without BOM, LF,
    2-space indent (the layout JavaScript's JSON.stringify(x, null, 2) writes)."""
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = os.path.join(os.path.dirname(p), ".practices.json.%d.%d.tmp" % (os.getpid(), int(time.time() * 1000)))
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, p)


def _entries(data):
    return [e for e in data["practices"] if isinstance(e, dict)]


def current():
    """The practices that aren't retired ([] when the file is missing or broken: they are advice)."""
    try:
        return [e for e in _entries(_load()) if not e.get("retired") and e.get("practice")]
    except K.KnowledgeError:
        return []


def _clean(text):
    """One line, checked: not empty, no private data, no job data (a practice holds on every job)."""
    text = P.one_line(text)
    if not text:
        raise K.KnowledgeError("text is required: the practice, one line.")
    problems = K.job_data_problems(text)
    if problems:
        raise K.KnowledgeError("Not saved: a practice holds on every job, but this one has %s. Facts about one job go "
                               "in tbc_project_notes action=add (ask the user first)." % "; ".join(problems))
    return text


def _topics(topics):
    if topics is None:
        return None
    if isinstance(topics, str):
        topics = [topics]
    if not isinstance(topics, list) or not all(isinstance(t, str) for t in topics):
        raise K.KnowledgeError("topics must be a list of words, e.g. ['storm', 'slope'].")
    return [P.one_line(t).lower() for t in topics if P.one_line(t)]


def list_practices(include_retired=False):
    """action=list: the practices (retired ones too when asked), with the file's path."""
    data = _load()
    items = _entries(data) if include_retired else [e for e in _entries(data) if not e.get("retired")]
    return {"practices": items, "file": path(),
            "hint": "Shared by Project Analyzer, Civil 3D MCP and TBC MCP. Only entries with source 'tbc' can be changed "
                    "here; correct another tool's practice by adding one (ask the user first)."}


def search(query, limit=20):
    """action=search: current practices matching the words (text and topics), best first."""
    if not K._tokens(query):
        raise K.KnowledgeError("query is required")
    hits = []
    for e in current():
        s = K._score(query, e.get("practice"), " ".join(str(t) for t in e.get("topics") or []))
        if s:
            hits.append((s, e))
    hits.sort(key=lambda h: -h[0])
    return {"query": query, "practices": [e for _, e in hits[:int(limit)]]}


def add(text, topics=None):
    """action=add: a new practice with source 'tbc'; the same text (any case) among the current ones comes back
    unchanged."""
    text = _clean(text)
    topics = _topics(topics) or []
    data = _load()  # re-read right before writing
    for e in _entries(data):
        if not e.get("retired") and str(e.get("practice", "")).strip().lower() == text.lower():
            return {"success": True, "action": "unchanged", "practice": e}
    numbers = [int(m.group(1)) for e in _entries(data) for m in [re.match(r"^practice-(\d+)$", str(e.get("id", "")))] if m]
    entry = {"id": "practice-%d" % (max(numbers + [0]) + 1), "practice": text, "topics": topics, "source": SOURCE,
             "added": P._now()}
    data["practices"].append(entry)
    _save(data)
    return {"success": True, "action": "added", "practice": entry, "file": path()}


def _own(data, pid):
    entry = next((e for e in _entries(data) if e.get("id") == pid), None)
    if not entry:
        raise K.KnowledgeError("No practice %r." % pid)
    if entry.get("source") != SOURCE:
        raise K.KnowledgeError("%s was added by %s, which owns it. Correct it by adding a new practice (ask the user "
                               "first)." % (pid, P.TOOL_LABELS.get(entry.get("source"), entry.get("source") or "another tool")))
    if entry.get("retired"):
        raise K.KnowledgeError("%s was removed on %s." % (pid, entry["retired"]))
    return entry


def update(pid, text=None, topics=None):
    """action=update: change one of TBC's own practices (text and/or topics) and stamp 'updated'."""
    text = _clean(text) if text is not None else None
    topics = _topics(topics)
    if text is None and topics is None:
        raise K.KnowledgeError("Give text and/or topics to change.")
    data = _load()
    entry = _own(data, pid)
    if text is not None:
        entry["practice"] = text
    if topics is not None:
        entry["topics"] = topics
    entry["updated"] = P._now()
    _save(data)
    return {"success": True, "action": "updated", "practice": entry}


def remove(pid):
    """action=remove: retire one of TBC's own practices (kept, hidden, its id never reused)."""
    data = _load()
    entry = _own(data, pid)
    entry["retired"] = P._now()
    _save(data)
    return {"success": True, "action": "removed", "practice": entry}


def practices_text():
    """The current practices as the block the server appends to its instructions; '' when there are none."""
    items = current()
    if not items:
        return ""
    lines = ["- [%s] %s" % (e.get("id"), e["practice"]) for e in items[:MAX_SHOWN]]
    if len(items) > MAX_SHOWN:
        lines.append("- ... %d more: tbc_practices action=search" % (len(items) - MAX_SHOWN))
    return ("GOOD PRACTICES (engineering and company practice shared by Project Analyzer, Civil 3D MCP and TBC MCP; "
            "follow them on every job unless the job's facts say otherwise):\n" + "\n".join(lines))
