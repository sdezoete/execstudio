"""Text extraction from uploaded files, standard library only.

Supported: .docx, .pptx, .xlsx (Office Open XML), .csv, .txt, .md, and .pdf when
the optional pypdf library is installed.
"""
import io
import re
import zipfile
import xml.etree.ElementTree as ET

try:
    from pypdf import PdfReader
    PDF_SUPPORTED = True
except BaseException as _e:  # optional dependency; a broken install must not stop the server
    if isinstance(_e, (KeyboardInterrupt, SystemExit)):
        raise
    PdfReader = None
    PDF_SUPPORTED = False

MAX_PDF_PAGES = 200

MAX_MEMBER_BYTES = 30 * 1024 * 1024   # guards against zip bombs
MAX_ROWS_PER_SHEET = 400

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


class ExtractError(Exception):
    pass


def extract(name, data):
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext in ("txt", "md", "csv"):
        return _text(data)
    if ext in ("docx", "pptx", "xlsx"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise ExtractError("This file is damaged or is not a real .%s file." % ext) from e
        with zf:
            return {"docx": _docx, "pptx": _pptx, "xlsx": _xlsx}[ext](zf)
    if ext == "pdf":
        if not PDF_SUPPORTED:
            raise ExtractError("PDF reading isn't installed on this server (pypdf). Upload the .docx or .pptx version, or paste the key facts.")
        return _pdf(data)
    if ext in ("doc", "ppt", "xls"):
        raise ExtractError("Older Office formats aren't supported. Save the file as .%sx and upload it again." % ext)
    raise ExtractError("Unsupported file type. Use .docx, .pptx, .xlsx, .csv, .txt or .md.")


def _pdf(data):
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as e:  # noqa: BLE001
                raise ExtractError("This PDF is password-protected. Remove the password and upload it again.") from e
        pages = []
        for i, page in enumerate(reader.pages[:MAX_PDF_PAGES], 1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append("Page %d:\n%s" % (i, text))
    except ExtractError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ExtractError("This PDF could not be read.") from e
    if not pages:
        raise ExtractError("This PDF has no selectable text (it may be a scan). Upload the original document instead.")
    return "\n\n".join(pages)


def _text(data):
    for enc in ("utf-8-sig", "utf-16", "cp1256", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read(zf, member):
    info = zf.getinfo(member)
    if info.file_size > MAX_MEMBER_BYTES:
        raise ExtractError("The file is too large to read.")
    return zf.read(member)


def _xml(zf, member):
    try:
        return ET.fromstring(_read(zf, member))
    except ET.ParseError as e:
        raise ExtractError("The file contains invalid XML.") from e


def _docx(zf):
    if "word/document.xml" not in zf.namelist():
        raise ExtractError("This .docx has no document body.")
    root = _xml(zf, "word/document.xml")
    paras = []
    for p in root.iter("{%s}p" % NS["w"]):
        text = "".join(t.text or "" for t in p.iter("{%s}t" % NS["w"]))
        if text.strip():
            paras.append(text.strip())
    return "\n".join(paras)


def _pptx(zf):
    names = [n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)]
    names.sort(key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    out = []
    for i, n in enumerate(names, 1):
        root = _xml(zf, n)
        paras = []
        for p in root.iter("{%s}p" % NS["a"]):
            text = "".join(t.text or "" for t in p.iter("{%s}t" % NS["a"]))
            if text.strip():
                paras.append(text.strip())
        out.append("Slide %d:\n%s" % (i, "\n".join(paras)))
        notes = "ppt/notesSlides/notesSlide%d.xml" % i
        if notes in zf.namelist():
            nroot = _xml(zf, notes)
            ntext = " ".join((t.text or "").strip() for t in nroot.iter("{%s}t" % NS["a"]) if (t.text or "").strip())
            if ntext and not ntext.isdigit():
                out.append("Speaker notes: " + ntext)
    return "\n\n".join(out)


def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref or "A").group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _xlsx(zf):
    names = zf.namelist()
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in _xml(zf, "xl/sharedStrings.xml").iter("{%s}si" % NS["s"]):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["s"])))

    # sheet names in workbook order
    sheets = []
    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for rel in _xml(zf, "xl/_rels/workbook.xml.rels"):
            rels[rel.get("Id")] = rel.get("Target")
    if "xl/workbook.xml" in names:
        for sh in _xml(zf, "xl/workbook.xml").iter("{%s}sheet" % NS["s"]):
            target = rels.get(sh.get("{%s}id" % NS["r"]), "")
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            sheets.append((sh.get("name"), target))

    out = []
    for title, path in sheets:
        if path not in names:
            continue
        rows = []
        for row in _xml(zf, path).iter("{%s}row" % NS["s"]):
            cells = {}
            for c in row.iter("{%s}c" % NS["s"]):
                t = c.get("t")
                v = c.find("{%s}v" % NS["s"])
                if t == "s" and v is not None and v.text is not None:
                    idx = int(v.text)
                    val = shared[idx] if idx < len(shared) else ""
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["s"]))
                else:
                    val = v.text if v is not None and v.text is not None else ""
                if val != "":
                    cells[_col_index(c.get("r"))] = val
            if cells:
                width = max(cells) + 1
                rows.append(",".join(_csv(cells.get(i, "")) for i in range(width)))
            if len(rows) >= MAX_ROWS_PER_SHEET:
                rows.append("[further rows omitted]")
                break
        if rows:
            out.append("Sheet: %s\n%s" % (title, "\n".join(rows)))
    return "\n\n".join(out)


def _csv(v):
    v = str(v)
    if any(ch in v for ch in ',"\n'):
        return '"' + v.replace('"', '""') + '"'
    return v
