# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
"""
Text of Word, Excel and PowerPoint files (.docx, .xlsx, .pptx) with nothing but the standard library.

Used for the job's user knowledge (projects.py) when Project Analyzer hasn't read a document into the project
database (it isn't installed, or hasn't run since the document was added). These files are zip archives of XML; the
text is taken from the XML as Markdown-ish plain text:

    .docx   word/document.xml: one line per paragraph, table cells joined with " | ", tabs and breaks kept
    .pptx   ppt/slides/slideN.xml in slide order: "## Slide N", then one line per paragraph
    .xlsx   every sheet in workbook order: "## <sheet name>", then one line per row, cells joined with " | "
            (shared strings and inline strings resolved; formulas show their last computed value)

No formatting, images or embedded objects. Members bigger than MAX_MEMBER_BYTES (uncompressed) are skipped, so a
damaged or hostile file can't fill the memory. Raises OfficeTextError for a file that isn't a readable zip.
"""
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

EXTENSIONS = (".docx", ".xlsx", ".pptx")
MAX_MEMBER_BYTES = 64 * 1024 * 1024

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


class OfficeTextError(Exception):
    pass


def _xml(z, name):
    """The parsed XML member `name`, or None when it is missing or too big."""
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_MEMBER_BYTES:
        return None
    return ET.fromstring(z.read(info))


def _paragraphs(root, ns):
    """Text of each paragraph (<w:p> or <a:p>) under root, in order."""
    out = []
    for p in root.iter(ns + "p"):
        parts = []
        for el in p.iter():
            if el.tag == ns + "t" and el.text:
                parts.append(el.text)
            elif el.tag in (ns + "tab",):
                parts.append("\t")
            elif el.tag in (ns + "br", ns + "cr"):
                parts.append("\n")
        out.append("".join(parts))
    return out


def _docx(z):
    root = _xml(z, "word/document.xml")
    if root is None:
        raise OfficeTextError("no word/document.xml")
    body = root.find(_W + "body")
    lines = []
    for block in (body if body is not None else []):
        if block.tag == _W + "p":
            lines.extend(_paragraphs(block, _W))
        elif block.tag == _W + "tbl":
            for row in block.iter(_W + "tr"):
                cells = [" ".join(t for t in _paragraphs(c, _W) if t) for c in row.findall(_W + "tc")]
                lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _pptx(z):
    names = [n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)]
    names.sort(key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    out = []
    for i, name in enumerate(names, 1):
        root = _xml(z, name)
        if root is None:
            continue
        text = [t for t in _paragraphs(root, _A) if t.strip()]
        out.append("## Slide %d\n\n%s" % (i, "\n".join(text)))
    return "\n\n".join(out)


def _cell_text(c, shared):
    kind = c.get("t")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in c.iter(_S + "t"))
    v = c.find(_S + "v")
    if v is None or v.text is None:
        return ""
    if kind == "s":
        try:
            return shared[int(v.text)]
        except (ValueError, IndexError):
            return ""
    if kind == "b":
        return "TRUE" if v.text == "1" else "FALSE"
    return v.text


def _xlsx(z):
    shared = []
    sst = _xml(z, "xl/sharedStrings.xml")
    if sst is not None:
        shared = ["".join(t.text or "" for t in si.iter(_S + "t")) for si in sst.findall(_S + "si")]
    book = _xml(z, "xl/workbook.xml")
    rels = _xml(z, "xl/_rels/workbook.xml.rels")
    targets = {}
    if rels is not None:
        for r in rels.findall(_REL + "Relationship"):
            target = r.get("Target", "")
            targets[r.get("Id")] = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
                posixpath.join("xl", target))
    sheets = []
    if book is not None:
        for s in book.iter(_S + "sheet"):
            path = targets.get(s.get(_R + "id"))
            if path:
                sheets.append((s.get("name") or path, path))
    if not sheets:
        sheets = [(n, n) for n in sorted(z.namelist()) if re.match(r"xl/worksheets/sheet\d+\.xml$", n)]
    out = []
    for name, path in sheets:
        root = _xml(z, path)
        if root is None:
            continue
        rows = []
        for row in root.iter(_S + "row"):
            cells = [_cell_text(c, shared) for c in row.findall(_S + "c")]
            if any(cells):
                rows.append(" | ".join(cells))
        out.append("## %s\n\n%s" % (name, "\n".join(rows)))
    return "\n\n".join(out)


def read(path):
    """The text of a .docx, .xlsx or .pptx file (by extension). OfficeTextError when it can't be read."""
    ext = posixpath.splitext(path.replace("\\", "/"))[1].lower()
    reader = {".docx": _docx, ".xlsx": _xlsx, ".pptx": _pptx}.get(ext)
    if not reader:
        raise OfficeTextError("not a .docx, .xlsx or .pptx file")
    try:
        with zipfile.ZipFile(path) as z:
            return reader(z)
    except (zipfile.BadZipFile, ET.ParseError, OSError, RuntimeError) as ex:
        raise OfficeTextError(str(ex) or type(ex).__name__)
