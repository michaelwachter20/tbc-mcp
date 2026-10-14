# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Knowledge store for the TBC MCP server (modelled on civil3d-mcp-unified's skills + saved scripts,
plus a memory of lessons learned and auto-recorded command panel layouts).

Layout (default: <repo>/knowledge, override with TBC_MCP_KNOWLEDGE_DIR):
  skills/<category>/<name>.skill.md   documented how-tos with frontmatter
  scripts/<name>.py                   saved IronPython scripts with a JSON metadata header
  memory/lessons.jsonl                one lesson per line: {id, ts, topic, tags, text, tbc_version}
  commands/<key>.json                 TBC command panel layouts seen by command_ui_*, plus notes

TBC VERSIONS: everything here records the TBC release it was verified on (baseline: 2026.10, build 44.0.9666).
When a newer TBC behaves differently, knowledge is ADDED for that release and never deleted:
  - skills: frontmatter tbc_versions + a '## TBC <release>' section appended (append_version_section)
  - lessons: new lessons carry the current release; old ones stay
  - command layouts: a different release's layout goes under 'versions' -> {release: layout}; the original stays
  - scripts: script_version increments on every save; the previous file is archived in scripts/_archive/
"""
import datetime
import json
import os
import re

ROOT = os.environ.get("TBC_MCP_KNOWLEDGE_DIR") or os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge"))
SKILLS = os.path.join(ROOT, "skills")
SCRIPTS = os.path.join(ROOT, "scripts")
MEMORY = os.path.join(ROOT, "memory", "lessons.jsonl")
COMMANDS = os.path.join(ROOT, "commands")

NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")
SCRIPT_HEADER = "tbc-script"
ARCHIVE = os.path.join(SCRIPTS, "_archive")

# ---------------------------------------------------------------------------
# TBC version the knowledge applies to
# ---------------------------------------------------------------------------
BASELINE_RELEASE = "2026.10"            # everything written before versioning was verified on this release
BASELINE_BUILD = "44.0.9666.28609"
_tbc = {"release": None, "build": None}  # set by the server once it has asked TBC (set_tbc_version)

VERSION_RULE = ("Verified on TBC %s. If something here does not work on a newer TBC release, ADD a section "
                "'## TBC <release>' (tbc_skills action=append_version_section) with what changed - never delete or "
                "rewrite the %s information.")


def set_tbc_version(release, build=None):
    _tbc["release"], _tbc["build"] = release, build


def current_release():
    return _tbc["release"] or BASELINE_RELEASE


def version_note(versions):
    """Warning for knowledge verified on other releases than the running TBC, else None."""
    versions = versions or [BASELINE_RELEASE]
    cur = _tbc["release"]
    if cur and cur not in versions:
        return ("Verified on TBC %s; this TBC is %s. Check it still works; if not, ADD a '## TBC %s' section "
                "(do not delete the old one)." % (", ".join(versions), cur, cur))
    return None


class KnowledgeError(Exception):
    pass


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _check_name(name, what="name"):
    if not name or not NAME_RE.match(name):
        raise KnowledgeError("%s must be 1-80 chars of letters, digits, '_' or '-': %r" % (what, name))


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def _read(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def _tokens(s):
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) > 1]


def _score(query, *texts):
    q = _tokens(query)
    if not q:
        return 0
    hay = " ".join(t or "" for t in texts).lower()
    score = sum(hay.count(t) for t in q)
    if all(t in hay for t in q):
        score += 10 * len(q)
    return score


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------
def parse_frontmatter(text):
    lines = text.splitlines()
    i = 0
    while i < len(lines) and lines[i].strip() == "---":
        i += 1  # tolerate a doubled opening '---'
    if i == 0:
        return {}, text
    meta = {}
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip()
            try:
                meta[k.strip()] = json.loads(v)
            except ValueError:
                meta[k.strip()] = v.strip('"').strip("'")
        i += 1
    return meta, "\n".join(lines[i + 1:]).lstrip("\n")


def _skill_files():
    for dp, _, fns in os.walk(SKILLS):
        for fn in fns:
            if fn.endswith(".skill.md"):
                yield os.path.join(dp, fn)


def _skill_info(path):
    meta, body = parse_frontmatter(_read(path))
    name = meta.get("name") or os.path.basename(path)[:-len(".skill.md")]
    versions = meta.get("tbc_versions") or [BASELINE_RELEASE]
    info = {"name": name, "category": meta.get("category") or os.path.basename(os.path.dirname(path)),
            "description": meta.get("description", ""), "requires_write": bool(meta.get("requires_write", False)),
            "verified": meta.get("verified"), "tbc_versions": versions, "path": path}
    note = version_note(versions)
    if note:
        info["version_note"] = note
    return info, body


def list_skills(category=None):
    out = []
    for p in sorted(_skill_files()):
        info, _ = _skill_info(p)
        if category and info["category"] != category:
            continue
        info.pop("path")
        out.append(info)
    return out


def _skill_path(name):
    for p in _skill_files():
        info, body = _skill_info(p)
        if info["name"] == name or os.path.basename(p) == name + ".skill.md":
            return p
    return None


def read_skill(name):
    p = _skill_path(name)
    if not p:
        raise KnowledgeError("No skill named %r. Use tbc_skills action=list or search." % name)
    text = _read(p)
    info, _ = _skill_info(p)
    if info.get("version_note"):
        text = "> VERSION NOTE: " + info["version_note"] + "\n\n" + text
    return text


def save_skill(name, category, description, body, requires_write=False, parameters=None, overwrite=False):
    _check_name(name)
    _check_name(category, "category")
    if not body or not body.strip():
        raise KnowledgeError("body is required (markdown: when to use, steps/code, gotchas)")
    path = os.path.join(SKILLS, category, name + ".skill.md")
    rel = current_release()
    if os.path.exists(path):
        if not overwrite:
            raise KnowledgeError("Skill %r already exists; pass overwrite=true to replace it." % name)
        old = parse_frontmatter(_read(path))[0].get("tbc_versions") or [BASELINE_RELEASE]
        if rel not in old:
            raise KnowledgeError("Skill %r holds knowledge for TBC %s; this is TBC %s. Do not overwrite it: use "
                                 "action=append_version_section to ADD what is different on %s." % (name, ", ".join(old), rel, rel))
    fm = ["---", "name: " + name, "category: " + category, "description: " + json.dumps(description or ""),
          "requires_write: " + ("true" if requires_write else "false"),
          "parameters: " + json.dumps(parameters or []), "tbc_versions: " + json.dumps([rel]),
          "updated: " + _now(), "---", "", "> " + VERSION_RULE % (rel, rel), ""]
    _write(path, "\n".join(fm) + body.strip() + "\n")
    return {"saved": path, "tbc_version": rel}


def append_version_section(name, body, release=None):
    """ADD a '## TBC <release>' section to a skill (for a TBC release that behaves differently). Never removes the
    existing sections; records the release in the frontmatter tbc_versions."""
    p = _skill_path(name)
    if not p:
        raise KnowledgeError("No skill named %r" % name)
    if not body or not body.strip():
        raise KnowledgeError("body is required: what is different on this release")
    rel = release or current_release()
    text = _read(p)
    meta, _ = parse_frontmatter(text)
    versions = meta.get("tbc_versions") or [BASELINE_RELEASE]
    if rel not in versions:
        versions = versions + [rel]
        if re.search(r"^tbc_versions:.*$", text, re.M):
            text = re.sub(r"^tbc_versions:.*$", "tbc_versions: " + json.dumps(versions), text, count=1, flags=re.M)
        else:
            text = re.sub(r"^(name: .*)$", r"\1\ntbc_versions: " + json.dumps(versions).replace("\\", "\\\\"), text, count=1, flags=re.M)
    text = text.rstrip("\n") + "\n\n## TBC %s (added %s)\n\n%s\n" % (rel, _now()[:10], body.strip())
    _write(p, text)
    return {"appended": "TBC " + rel, "skill": name, "tbc_versions": versions}


# ---------------------------------------------------------------------------
# scripts
# ---------------------------------------------------------------------------
def parse_script(text):
    m = re.match(r'\s*(?:"""|\'\'\')\s*' + SCRIPT_HEADER + r'\s*\n(.*?)(?:"""|\'\'\')', text, re.S)
    if not m:
        raise KnowledgeError("Script is missing its metadata header (docstring starting with '%s')" % SCRIPT_HEADER)
    try:
        meta = json.loads(m.group(1))
    except ValueError as ex:
        raise KnowledgeError("Bad JSON in script header: %s" % ex)
    return meta, text[m.end():].lstrip("\n")


def _script_path(name):
    _check_name(name)
    return os.path.join(SCRIPTS, name + ".py")


def list_scripts():
    out = []
    if not os.path.isdir(SCRIPTS):
        return out
    for fn in sorted(os.listdir(SCRIPTS)):
        if fn.endswith(".py"):
            try:
                meta, _ = parse_script(_read(os.path.join(SCRIPTS, fn)))
                rec = {"name": meta.get("name", fn[:-3]), "description": meta.get("description", ""),
                       "mode": meta.get("mode", "read"), "script_version": meta.get("script_version", 1),
                       "tbc_versions": meta.get("tbc_versions") or [BASELINE_RELEASE],
                       "parameters": [p.get("name") for p in meta.get("parameters", [])]}
                note = version_note(rec["tbc_versions"])
                if note:
                    rec["version_note"] = note
                out.append(rec)
            except KnowledgeError as ex:
                out.append({"name": fn[:-3], "error": str(ex)})
    return out


def read_script(name):
    p = _script_path(name)
    if not os.path.exists(p):
        raise KnowledgeError("No script named %r" % name)
    return _read(p)


def build_script(name, description, mode, parameters, code):
    if mode not in ("read", "write"):
        raise KnowledgeError("mode must be 'read' or 'write'")
    for prm in parameters or []:
        if not prm.get("name") or prm.get("type") not in ("string", "number", "integer", "boolean", "array", "object"):
            raise KnowledgeError("each parameter needs a name and type (string|number|integer|boolean|array|object): %r" % prm)
    meta = {"name": name, "description": description or "", "mode": mode, "parameters": parameters or [],
            "script_version": 1, "tbc_versions": [current_release()], "tbc_build": _tbc["build"] or BASELINE_BUILD,
            "updated": _now()}
    header = '"""' + SCRIPT_HEADER + "\n" + json.dumps(meta, indent=1) + '\n"""\n'
    return header + code.strip("\n") + "\n"


def _with_meta(text, **changes):
    meta, code = parse_script(text)
    meta.update(changes)
    return '"""' + SCRIPT_HEADER + "\n" + json.dumps(meta, indent=1) + '\n"""\n' + code


def save_script(name, text, overwrite=False):
    """Save a script. Versioning: script_version starts at 1 and goes up by one on every overwrite; the previous
    file is kept as scripts/_archive/<name>.v<N>.py (never deleted). tbc_versions lists the TBC releases the
    script was saved/tested on: saving on a new release adds that release, the old ones stay listed."""
    p = _script_path(name)
    meta, _ = parse_script(text)
    if os.path.exists(p):
        if not overwrite:
            raise KnowledgeError("Script %r already exists; pass overwrite=true to save a new version of it." % name)
        old_text = _read(p)
        old = parse_script(old_text)[0]
        n = int(old.get("script_version", 1))
        _write(os.path.join(ARCHIVE, "%s.v%d.py" % (name, n)), old_text)
        versions = list(old.get("tbc_versions") or [BASELINE_RELEASE])
        if current_release() not in versions:
            versions.append(current_release())
        text = _with_meta(text, script_version=n + 1, tbc_versions=versions, previous_version_archived="_archive/%s.v%d.py" % (name, n))
    else:
        text = _with_meta(text, script_version=meta.get("script_version", 1),
                          tbc_versions=meta.get("tbc_versions") or [current_release()])
    _write(p, text)
    return {"saved": p, "script_version": parse_script(text)[0]["script_version"]}


def delete_script(name):
    """Retire a script: it is moved to scripts/_archive (kept for older TBC releases), not destroyed."""
    p = _script_path(name)
    if not os.path.exists(p):
        raise KnowledgeError("No script named %r" % name)
    text = _read(p)
    n = int(parse_script(text)[0].get("script_version", 1))
    _write(os.path.join(ARCHIVE, "%s.v%d.retired.py" % (name, n)), text)
    os.remove(p)
    return {"retired": name, "archived_as": "_archive/%s.v%d.retired.py" % (name, n)}


def bind_args(meta, given):
    """Validate/coerce run arguments against the script's declared parameters."""
    given = dict(given or {})
    out = {}
    conv = {"number": float, "integer": int, "string": str}
    for prm in meta.get("parameters", []):
        n = prm["name"]
        if n in given:
            v = given.pop(n)
            t = prm.get("type")
            try:
                if t in conv and v is not None:
                    v = conv[t](v)
                elif t == "boolean" and isinstance(v, str):
                    v = v.strip().lower() in ("1", "true", "yes", "on")
            except (TypeError, ValueError):
                raise KnowledgeError("parameter %r should be %s, got %r" % (n, t, v))
            out[n] = v
        elif "default" in prm:
            out[n] = prm["default"]
        elif prm.get("required"):
            raise KnowledgeError("missing required parameter %r (%s)" % (n, prm.get("description", "")))
    if given:
        raise KnowledgeError("unknown parameter(s) %s; declared: %s" % (sorted(given), [p["name"] for p in meta.get("parameters", [])]))
    return out


# ---------------------------------------------------------------------------
# memory (lessons learned)
# ---------------------------------------------------------------------------
def _lessons():
    if not os.path.exists(MEMORY):
        return []
    out = []
    with open(MEMORY, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def add_lesson(text, topic=None, tags=None):
    if not text or not text.strip():
        raise KnowledgeError("text is required")
    ls = _lessons()
    lid = max([l.get("id", 0) for l in ls] + [0]) + 1
    rec = {"id": lid, "ts": _now(), "topic": (topic or "general").strip().lower(), "tags": tags or [], "text": text.strip(),
           "tbc_version": current_release()}
    os.makedirs(os.path.dirname(MEMORY), exist_ok=True)
    with open(MEMORY, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def list_lessons(topic=None):
    ls = _lessons()
    if topic:
        ls = [l for l in ls if l.get("topic") == topic.strip().lower()]
    return ls


def delete_lesson(lid):
    """Delete a lesson that turned out to be WRONG on its own release. A lesson recorded on another TBC release is
    never deleted (it is still true there): add a new lesson for the current release instead."""
    ls = _lessons()
    keep = [l for l in ls if l.get("id") != int(lid)]
    if len(keep) == len(ls):
        raise KnowledgeError("No lesson with id %s" % lid)
    gone = [l for l in ls if l.get("id") == int(lid)][0]
    if gone.get("tbc_version", BASELINE_RELEASE) != current_release():
        raise KnowledgeError("Lesson %s was recorded on TBC %s (this is %s). Keep it; add a lesson for %s with what "
                             "is different." % (lid, gone.get("tbc_version", BASELINE_RELEASE), current_release(), current_release()))
    _write(MEMORY, "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in keep))
    return {"deleted": int(lid)}


# ---------------------------------------------------------------------------
# remembered command panels
# ---------------------------------------------------------------------------
def _cmd_path(key):
    return os.path.join(COMMANDS, re.sub(r"[^A-Za-z0-9_\-.]", "_", key.lower()) + ".json")


def get_command(key):
    p = _cmd_path(key)
    if os.path.exists(p):
        try:
            return json.loads(_read(p))
        except ValueError:
            return None
    return None


# Dropdowns whose entries come from the user's project (layer, surface, style, block names, folders ...): their
# options are NOT recorded - they are project data and must not end up in a shared knowledge base.
PROJECT_LIST_RE = re.compile(r"layer|surface|style|block|folder|plan ?set|sheet ?set|feature|template|corridor|"
                             r"alignment|boundary|library|font|recent|path|file|profile|point ?id|name|attr|code|"
                             r"selection|source|target|lyr|filter|cbo(?:Attr|Field)", re.I)


def _project_list(f):
    if not (f.get("label") or "").strip():
        return True  # unlabelled dropdown: purpose unknown, so treat its entries as project data
    return bool(PROJECT_LIST_RE.search("%s %s" % (f.get("id") or "", f.get("label") or "")))


def record_command(state):
    """Store the field/button layout of a command panel (keeps existing notes). Options of project-data dropdowns
    (layers, surfaces, styles ...) are not stored, so no project or user data reaches the knowledge base."""
    c = state.get("command")
    if not c:
        return None
    old = get_command(c["key"]) or {}
    fields = []
    for f in state.get("fields", []):
        d = {"id": f.get("id"), "label": f.get("label"), "kind": f.get("kind")}
        if f.get("options"):
            if _project_list(f):
                d["options"] = "project data (not recorded)"
            else:
                d["options_sample"] = f["options"][:8]
                d["option_count"] = len(f["options"])
        fields.append(d)
    layout = {"caption": c.get("caption"), "last_seen": _now(), "fields": fields,
              "buttons": [b.get("text") for b in state.get("buttons", [])]}
    rel = current_release()
    if old and old.get("tbc_version", BASELINE_RELEASE) != rel:
        # a different TBC release: keep the original layout, add this release's next to it
        rec = old
        rec.setdefault("versions", {})[rel] = layout
    else:
        rec = dict(layout, key=c["key"], tbc_version=rel, notes=old.get("notes", []))
        if old.get("versions"):
            rec["versions"] = old["versions"]
    _write(_cmd_path(c["key"]), json.dumps(rec, indent=1, ensure_ascii=False))
    return rec


def add_command_note(key, text):
    rec = get_command(key) or {"key": key, "fields": [], "buttons": [], "notes": []}
    rec.setdefault("notes", []).append({"ts": _now(), "text": text.strip(), "tbc_version": current_release()})
    _write(_cmd_path(key), json.dumps(rec, indent=1, ensure_ascii=False))
    return rec


def remembered_for_command(key):
    rec = get_command(key) or {}
    tag = lambda v: "" if (v or BASELINE_RELEASE) == current_release() else "[TBC %s] " % (v or BASELINE_RELEASE)
    lessons = [tag(l.get("tbc_version")) + l["text"] for l in list_lessons(key.lower())]
    notes = [tag(n.get("tbc_version")) + n["text"] for n in rec.get("notes", [])]
    return {"notes": notes + lessons} if (notes or lessons) else None


# ---------------------------------------------------------------------------
# user preferences (standing rules; injected into the server instructions for every AI)
# ---------------------------------------------------------------------------
PREFS = os.path.join(ROOT, "preferences.json")


def list_prefs():
    if not os.path.exists(PREFS):
        return []
    try:
        return json.loads(_read(PREFS))
    except ValueError:
        return []


def add_pref(text, topic=None):
    if not text or not text.strip():
        raise KnowledgeError("text is required")
    ps = list_prefs()
    pid = max([p.get("id", 0) for p in ps] + [0]) + 1
    rec = {"id": pid, "topic": (topic or "general").strip().lower(), "text": text.strip(), "added": _now()}
    ps.append(rec)
    _write(PREFS, json.dumps(ps, indent=1, ensure_ascii=False))
    return rec


def update_pref(pid, text):
    ps = list_prefs()
    for p in ps:
        if p.get("id") == int(pid):
            p["text"] = text.strip()
            p["updated"] = _now()
            _write(PREFS, json.dumps(ps, indent=1, ensure_ascii=False))
            return p
    raise KnowledgeError("No preference with id %s" % pid)


def remove_pref(pid):
    ps = list_prefs()
    keep = [p for p in ps if p.get("id") != int(pid)]
    if len(keep) == len(ps):
        raise KnowledgeError("No preference with id %s" % pid)
    _write(PREFS, json.dumps(keep, indent=1, ensure_ascii=False))
    return {"removed": int(pid)}


def prefs_text():
    ps = list_prefs()
    if not ps:
        return ""
    return "USER PREFERENCES (standing rules from the user - always follow them):\n" + "\n".join(
        "- [%s] %s" % (p["topic"], p["text"]) for p in ps)


# ---------------------------------------------------------------------------
# unified search
# ---------------------------------------------------------------------------
def search(query, kinds=None, limit=15):
    kinds = kinds or ["skill", "script", "lesson", "command"]
    hits = []
    if "skill" in kinds:
        for p in _skill_files():
            info, body = _skill_info(p)
            s = _score(query, info["name"], info["name"], info["description"], info["category"], body)
            if s:
                h = {"type": "skill", "name": info["name"], "category": info["category"],
                     "description": info["description"], "tbc_versions": info["tbc_versions"]}
                if info.get("version_note"):
                    h["version_note"] = info["version_note"]
                hits.append((s, h))
    if "script" in kinds:
        for sc in list_scripts():
            s = _score(query, sc["name"], sc["name"], sc.get("description", ""))
            if s:
                hits.append((s, dict(sc, type="script")))
    if "lesson" in kinds:
        for l in _lessons():
            s = _score(query, l.get("topic"), l.get("text"), " ".join(l.get("tags", [])))
            if s:
                hits.append((s, {"type": "lesson", "id": l["id"], "topic": l["topic"], "text": l["text"],
                                 "tbc_version": l.get("tbc_version", BASELINE_RELEASE)}))
    if "command" in kinds and os.path.isdir(COMMANDS):
        for fn in os.listdir(COMMANDS):
            try:
                rec = json.loads(_read(os.path.join(COMMANDS, fn)))
            except Exception:
                continue
            labels = " ".join((f.get("label") or "") for f in rec.get("fields", []))
            notes = " ".join(n["text"] for n in rec.get("notes", []))
            s = _score(query, rec.get("key"), rec.get("caption"), labels, notes)
            if s:
                hits.append((s, {"type": "command", "key": rec["key"], "caption": rec.get("caption"),
                                 "tbc_version": rec.get("tbc_version", BASELINE_RELEASE),
                                 "other_versions": sorted(rec.get("versions", {})),
                                 "fields": [f.get("label") or f.get("id") for f in rec.get("fields", [])][:15],
                                 "notes": [n["text"] for n in rec.get("notes", [])][-5:]}))
    hits.sort(key=lambda h: -h[0])
    return [h[1] for h in hits[:limit]]
